"""
视频元数据获取。
B站 x/web-interface/view API → 标题、标签、简介、时长、播放量。
"""

from src.bilibili.client import get
from src.logger import debug, warning


def get_video_info(bvid: str) -> dict | None:
    """
    获取单个视频的元数据。

    返回:
        {
            "bvid": "BVxxx",
            "title": "...",
            "description": "...",
            "tags": ["tag1", "tag2"],
            "duration": 360,         # 秒
            "play_count": 12345,
            "danmaku_count": 233,
            "comment_count": 89,
            "cover_url": "https://...",
            "up_name": "UP主名",
            "up_mid": 123456,
        }
        失败返回 None。
    """
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    try:
        resp = get(url)
        data = resp.json()
        if data.get("code") != 0:
            warning("video", f"获取视频信息失败 [{bvid}]: code={data.get('code')}")
            return None
        v = data["data"]
        return {
            "bvid": bvid,
            "title": v.get("title", ""),
            "description": v.get("desc", ""),
            "tags": [t.get("tag_name", "") for t in v.get("tags", [])] if v.get("tags") else [],
            "duration": v.get("duration", 0),
            "play_count": v.get("stat", {}).get("view", 0),
            "danmaku_count": v.get("stat", {}).get("danmaku", 0),
            "comment_count": v.get("stat", {}).get("reply", 0),
            "cover_url": v.get("pic", ""),
            "up_name": v.get("owner", {}).get("name", ""),
            "up_mid": v.get("owner", {}).get("mid", 0),
            "cid": v.get("cid", 0),
        }
    except Exception as e:
        warning("video", f"获取视频信息异常 [{bvid}]: {e}")
        return None
