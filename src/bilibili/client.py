"""
B站 HTTP 客户端。
负责 Cookie 管理、CSRF 提取、请求头伪装、反反爬、Cookie 过期检测。
"""

import time
import requests

import config
from src.logger import debug, warning, error

# ── 请求头伪装（模拟真实 Chrome 浏览器）───────────────
_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# API 请求用更轻量的 Accept
_API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

_session = None
_csrf_token = None
_warmed_up = False


def _get_session() -> requests.Session:
    """获取或创建带 Cookie 的持久会话。首次创建时自动预热（访问B站首页获取基础 Cookie）。"""
    global _session, _warmed_up
    if _session is None:
        _session = requests.Session()
        _session.headers.update(_BASE_HEADERS)
        # 注入登录 Cookie
        cookies = {}
        if config.BILI_SESSDATA:
            cookies["SESSDATA"] = config.BILI_SESSDATA
        if config.BILI_CSRF:
            cookies["bili_jct"] = config.BILI_CSRF
        if config.BILI_DEDEUSERID:
            cookies["DedeUserID"] = config.BILI_DEDEUSERID
        if cookies:
            _session.cookies.update(cookies)
            debug("client", f"已加载 {len(cookies)} 个登录 Cookie")
        else:
            debug("client", "未设置 B站 Cookie（未登录模式，搜索仍可用）")
    if not _warmed_up:
        _warmup()
    return _session


def _warmup():
    """预热：访问 B站首页获取匿名 Cookie + 建立 TLS 指纹。"""
    global _warmed_up
    try:
        debug("client", "预热中：访问 B站首页...")
        resp = _session.get("https://www.bilibili.com/", timeout=10)
        _warmed_up = True
        debug("client", f"预热完成，状态码 {resp.status_code}，获取 {len(_session.cookies)} 个 Cookie")
    except Exception as e:
        warning("client", f"预热失败（非致命）: {e}")
        _warmed_up = True  # 不阻塞后续请求


def get_csrf() -> str:
    """获取 CSRF token（bili_jct）。优先环境变量，其次从 session cookie 取。"""
    global _csrf_token
    if _csrf_token:
        return _csrf_token
    if config.BILI_CSRF:
        _csrf_token = config.BILI_CSRF
        return _csrf_token
    sess = _get_session()
    for cookie in sess.cookies:
        if cookie.name == "bili_jct":
            _csrf_token = cookie.value
            debug("client", f"从 session 提取 CSRF: {_csrf_token[:4]}...")
            return _csrf_token
    error("client", "无法获取 CSRF token，评论发布将失败")
    return ""


def is_logged_in() -> bool:
    """检查是否已登录（有 SESSDATA + bili_jct）。"""
    return bool(config.BILI_SESSDATA) and bool(get_csrf())


def get(url: str, **kwargs) -> requests.Response:
    """发送 GET 请求，自动带 Cookie 和伪装头。API 请求使用更轻量的 Accept。"""
    sess = _get_session()
    # API 请求换轻量 Accept
    headers = {}
    if "api.bilibili.com" in url:
        headers.update(_API_HEADERS)
    if "search" in url:
        headers["Referer"] = "https://search.bilibili.com/"
    if "player" in url:
        headers["Referer"] = "https://www.bilibili.com/video/"
    resp = sess.get(url, headers=headers if headers else None,
                    timeout=kwargs.pop("timeout", 15), **kwargs)
    _check_cookie_expiry(resp)
    return resp


def post(url: str, data: dict | None = None, **kwargs) -> requests.Response:
    """发送 POST 请求，自动注入 CSRF token。"""
    sess = _get_session()
    if data is None:
        data = {}
    if "csrf" not in data:
        data["csrf"] = get_csrf()
    if "jsonp" not in data:
        data["jsonp"] = "jsonp"
    resp = sess.post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=kwargs.pop("timeout", 15),
        **kwargs,
    )
    _check_cookie_expiry(resp)
    return resp


def _check_cookie_expiry(resp: requests.Response):
    """检测 Cookie 是否过期（B站返回 -101）。"""
    try:
        body = resp.json()
        if body.get("code") == -101:
            error("client", "⚠️ Cookie 已过期（-101），需要重新获取 SESSDATA")
    except (ValueError, KeyError):
        pass  # 非 JSON 响应，忽略


def reset_session():
    """重置会话（Cookie 变更后调用）。"""
    global _session, _csrf_token
    _session = None
    _csrf_token = None
    debug("client", "会话已重置")
