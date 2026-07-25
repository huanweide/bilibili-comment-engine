"""
B站视频搜索。
搜索 API → BV 号列表 + 基础信息。
"""

from urllib.parse import quote

from src.bilibili.client import get
from src.logger import debug, warning


def search_videos(keyword: str, page: int = 1, order: str = "click") -> list[dict]:
    """
    搜索 B站视频。

    参数:
        keyword: 搜索关键词
        page: 页码（从 1 开始）
        order: 排序方式 — click(播放数) / pubdate(发布时间) / stow(收藏数)

    返回:
        [
            {
                "bvid": "BVxxx",
                "title": "...",
                "author": "...",
                "play_count": 12345,
                "danmaku_count": 233,
                "duration": "12:34",
                "url": "https://www.bilibili.com/video/BVxxx",
            },
            ...
        ]
    """
    encoded = quote(keyword)
    url = (
        f"https://api.bilibili.com/x/web-interface/search/type"
        f"?search_type=video&keyword={encoded}&page={page}&order={order}"
    )
    debug("search", f"搜索关键词 [{keyword}] page={page} order={order}")

    try:
        resp = get(url)
        data = resp.json()
        if data.get("code") != 0:
            warning("search", f"搜索失败: code={data.get('code')}, message={data.get('message')}")
            return []
        results = data.get("data", {}).get("result", [])
        videos = []
        for item in results:
            videos.append({
                "bvid": item.get("bvid", ""),
                "title": item.get("title", "").replace('<em class="keyword">', "").replace("</em>", ""),
                "author": item.get("author", ""),
                "play_count": item.get("play", 0),
                "danmaku_count": item.get("video_review", 0),
                "duration": item.get("duration", "00:00"),
                "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
            })
        debug("search", f"关键词 [{keyword}] 返回 {len(videos)} 个视频")
        return videos
    except Exception as e:
        warning("search", f"搜索异常 [{keyword}]: {e}")
        return []
