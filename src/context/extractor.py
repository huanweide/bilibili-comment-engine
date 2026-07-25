"""
上下文提取器。
收集视频的全部可理解信息：标题、标签、字幕、热评 → 结构化上下文。
"""

from src.bilibili.video import get_video_info
from src.bilibili.subtitle import extract_subtitle
from src.bilibili.comment import fetch_comments
from src.logger import debug, warning


def extract_context(bvid: str) -> dict | None:
    """
    提取单个视频的完整上下文。

    返回:
        {
            "bvid": "BVxxx",
            "video": { ... },        # get_video_info 返回的元数据
            "subtitle": "字幕文本",   # 可能为 None
            "hot_comments": [...],   # 热评列表，可能为空
            "has_subtitle": bool,     # 是否有字幕
            "has_comments": bool,     # 是否有热评
        }
        如果连视频元数据都拿不到（视频不存在/被删除），返回 None。
    """
    debug("extractor", f"提取上下文 [{bvid}]")

    # 1. 视频元数据（必须成功，否则跳过该视频）
    video = get_video_info(bvid)
    if video is None:
        warning("extractor", f"跳过 [{bvid}]: 无法获取视频信息")
        return None

    # 2. CC 字幕（可选，需要 cid）
    cid = video.get("cid", 0)
    subtitle = extract_subtitle(bvid, cid=cid)

    # 3. 热门评论（可选）
    hot_comments = fetch_comments(bvid)

    ctx = {
        "bvid": bvid,
        "video": video,
        "subtitle": subtitle,
        "hot_comments": hot_comments,
        "has_subtitle": subtitle is not None and len(subtitle) > 0,
        "has_comments": len(hot_comments) > 0,
    }
    debug("extractor", f"上下文提取完成 [{bvid}]: 字幕={'有' if ctx['has_subtitle'] else '无'}, "
                       f"热评={len(hot_comments)}条")
    return ctx
