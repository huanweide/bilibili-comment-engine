"""
B站评论读取与发布。
- fetch_comments(): 读取热门评论
- post_comment(): 发布评论（含反刷屏变体逻辑）
"""

import random
import time

from src.bilibili.client import get, post, get_csrf, is_logged_in
from src.logger import debug, warning, error
import config


# ── 读取 ───────────────────────────────────────────────

def fetch_comments(oid: str, count: int = None) -> list[dict]:
    """
    获取视频热门评论。

    参数:
        oid: BV 号对应的 oid（可直接用 bvid）
        count: 获取条数，默认取 HOT_COMMENT_COUNT 配置值

    返回:
        [
            {
                "rpid": "12345",
                "content": "...",
                "like_count": 233,
                "reply_count": 10,
                "user_name": "...",
                "publish_time": 1700000000,
            },
            ...
        ]
    """
    if count is None:
        count = config.HOT_COMMENT_COUNT
    url = f"https://api.bilibili.com/x/v2/reply/main?oid={oid}&type=1&mode=3&ps={count}"
    try:
        resp = get(url)
        data = resp.json()
        if data.get("code") != 0:
            warning("comment", f"获取评论失败 [{oid}]: code={data.get('code')}")
            return []
        replies = data.get("data", {}).get("replies", [])
        results = []
        for r in replies[:count]:
            results.append({
                "rpid": str(r.get("rpid", "")),
                "content": r.get("content", {}).get("message", ""),
                "like_count": r.get("like", 0),
                "reply_count": r.get("rcount", 0),
                "user_name": r.get("member", {}).get("uname", ""),
                "publish_time": r.get("ctime", 0),
            })
        debug("comment", f"获取 {len(results)} 条热评 [{oid}]")
        return results
    except Exception as e:
        warning("comment", f"获取评论异常 [{oid}]: {e}")
        return []


# ── 发布 ───────────────────────────────────────────────

# 反刷屏变体组件
_PREFIXES = [
    "", "说实话，", "补充一下，", "分享下，", "最近发现，",
    "有一说一，", "说句题外话，", "刷到这个视频让我想起，",
]
_SUFFIXES = ["👍", "✨", "💪", "🔥", "👌", "😄", "🙌", ""]

# 错误码映射
_ERROR_MAP = {
    0: "成功",
    -101: "账号异常/未登录",
    -111: "CSRF 校验失败",
    -404: "评论区关闭",
    10030: "评论区关闭",
    12013: "已评论过该视频",
    12019: "评论频率限制",
    12051: "重复评论/刷屏",
}


def post_comment(oid: str, message: str, variant_idx: int = 0) -> dict:
    """
    发布一条评论。

    参数:
        oid: 视频 oid（BV 号）
        message: 评论正文（不含变体前缀/后缀，由本函数自动添加）
        variant_idx: 变体序号，用于随机选前缀后缀

    返回:
        {
            "success": True/False,
            "code": 0,           # B站返回码
            "rpid": "xxx",       # 成功时的评论 ID
            "final_message": "实际发出的文本（含前后缀）",
            "error_msg": "",     # 失败时的错误描述
        }
    """
    if config.DRY_RUN:
        debug("comment", f"DRY_RUN 模式，跳过实际发布 [{oid}]: {message[:30]}...")
        return {"success": True, "code": 0, "rpid": "dry_run",
                "final_message": message, "error_msg": ""}

    if not is_logged_in():
        return {"success": False, "code": -1, "rpid": "", "final_message": message,
                "error_msg": "未登录，缺少 SESSDATA"}

    # 组装变体
    prefix = _PREFIXES[variant_idx % len(_PREFIXES)]
    suffix = _SUFFIXES[random.randint(0, len(_SUFFIXES) - 1)]
    final_msg = f"{prefix}{message}{suffix}"

    # 长度限制
    if len(final_msg) > 1000:
        final_msg = final_msg[:997] + "..."

    debug("comment", f"发布评论 [{oid}]: {final_msg[:50]}...")

    try:
        csrf = get_csrf()
        data = {
            "oid": oid,
            "type": "1",
            "message": final_msg,
            "csrf": csrf,
            "plat": "1",
        }
        resp = post("https://api.bilibili.com/x/v2/reply/add", data=data)
        body = resp.json()
        code = body.get("code", -999)
        error_label = _ERROR_MAP.get(code, f"未知错误 code={code}")

        if code == 0:
            rpid = str(body.get("data", {}).get("rpid", ""))
            debug("comment", f"[OK] 评论发布成功 [{oid}] rpid={rpid}")
            return {"success": True, "code": 0, "rpid": rpid,
                    "final_message": final_msg, "error_msg": ""}
        else:
            warning("comment", f"评论发布失败 [{oid}]: {error_label}")
            return {"success": False, "code": code, "rpid": "",
                    "final_message": final_msg, "error_msg": error_label}
    except Exception as e:
        error("comment", f"评论发布异常 [{oid}]: {e}")
        return {"success": False, "code": -999, "rpid": "",
                "final_message": final_msg, "error_msg": str(e)}


def classify_error(code: int) -> str:
    """
    分类 B站错误码。

    返回: "retry" (可重试) / "skip" (跳过该视频) / "stop" (停止运行)
    """
    if code in (0,):
        return "ok"
    if code in (12019,):  # 频率限制
        return "retry"
    if code in (12013, 12051, 10030, -404):  # 已评论 / 重复 / 关闭
        return "skip"
    if code in (-101, -111):  # 登录问题
        return "stop"
    return "skip"  # 未知错误，跳过保平安
