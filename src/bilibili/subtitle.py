"""
CC 字幕提取。
B站 player API → 字幕 JSON URL → 解析 → 纯文本。
MVP 阶段不做 ASR fallback（Phase 2 补）。
"""

import json

from src.bilibili.client import get
from src.logger import debug, warning
import config


def extract_subtitle(bvid: str, cid: int = 0) -> str | None:
    """
    提取视频 CC 字幕，返回纯文本。

    流程：player API → subtitle_list → 选中文/第一个 → 下载 JSON → 拼接文本
    字幕超过 SUBTITLE_MAX_CHARS 则截断。
    无字幕返回 None。
    """
    # 1. 获取视频 player 信息（需要 cid，否则 B站返回 -400）
    player_url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}" if cid else \
                 f"https://api.bilibili.com/x/player/v2?bvid={bvid}"
    try:
        resp = get(player_url)
        data = resp.json()
        if data.get("code") != 0:
            warning("subtitle", f"获取 player 信息失败 [{bvid}]: code={data.get('code')}")
            return None
    except Exception as e:
        warning("subtitle", f"player API 请求异常 [{bvid}]: {e}")
        return None

    # 2. 提取字幕列表
    subtitle_data = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
    if not subtitle_data:
        debug("subtitle", f"视频 [{bvid}] 无 CC 字幕")
        return None

    # 3. 选字幕：优先中文，其次第一个
    chosen = None
    for sub in subtitle_data:
        if "zh" in sub.get("lan_doc", "").lower() or "中文" in sub.get("lan_doc", ""):
            chosen = sub
            break
    if chosen is None:
        chosen = subtitle_data[0]

    subtitle_url = chosen.get("subtitle_url", "")
    if not subtitle_url:
        warning("subtitle", f"字幕条目无 URL [{bvid}]")
        return None

    # B站返回的 URL 可能是 // 开头，需要补 https:
    if subtitle_url.startswith("//"):
        subtitle_url = "https:" + subtitle_url

    debug("subtitle", f"下载字幕 [{bvid}]: {chosen.get('lan_doc', 'unknown')}")

    # 4. 下载并解析字幕 JSON
    try:
        resp = get(subtitle_url)
        subtitle_json = resp.json()
        body = subtitle_json.get("body", [])
        lines = []
        total_chars = 0
        for item in body:
            text = item.get("content", "")
            text_len = len(text)
            if total_chars + text_len > config.SUBTITLE_MAX_CHARS:
                remaining = config.SUBTITLE_MAX_CHARS - total_chars
                if remaining > 0:
                    lines.append(text[:remaining])
                break
            lines.append(text)
            total_chars += text_len

        full_text = "\n".join(lines)
        debug("subtitle", f"字幕提取完成 [{bvid}]: {len(lines)} 行, {total_chars} 字")
        return full_text if full_text.strip() else None
    except Exception as e:
        warning("subtitle", f"字幕下载/解析失败 [{bvid}]: {e}")
        return None
