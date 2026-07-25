"""
B站 LLM 评论引擎 — Web 服务器。
B站扫码登录 → 后端代理所有 API → 零配置，人人可用。
"""

import sys, os, json, time, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify, render_template, session
import config
from src.bilibili.search import search_videos
from src.context.extractor import extract_context
from src.llm.generator import generate_comment
from src.llm.planner import analyze_prompt
from src.dedup import get_stats, mark_processed, has_processed, get_processed_time, get_today_count, get_history
from src.logger import info, warning, error
import requests as req

app = Flask(__name__)
app.config["SECRET_KEY"] = "bce-" + os.urandom(16).hex()
app.config["SESSION_COOKIE_NAME"] = "bce_session"

# ── B站 API 请求头 ────────────────────────────────────
_BILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# ── B站 Cookie 管理 ───────────────────────────────────

def _bili_session():
    """从 Flask session 重建带 B站 Cookie 的 requests Session。"""
    s = req.Session()
    s.headers.update(_BILI_HEADERS.copy())
    d = session.get("bili_cookies", {})
    for name, value in d.items():
        s.cookies.set(name, value, domain=".bilibili.com")
    return s


def _save_bili_session(s: req.Session):
    """从 requests Session 提取 Cookie 存到 Flask session。"""
    cookies = {}
    for c in s.cookies:
        if c.name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
            cookies[c.name] = c.value
    session["bili_cookies"] = cookies
    session.modified = True


def _get_bili_cookie(name: str) -> str:
    """从 Flask session 取某个 B站 Cookie。"""
    return session.get("bili_cookies", {}).get(name, "")


# ── 工具函数 ───────────────────────────────────────────

def _llm_params(data: dict) -> dict:
    """
    从请求体中提取 LLM 配置参数。
    不读取请求头，API Key 仅通过 POST body 传递。
    """
    return {
        "api_key": data.get("api_key", "").strip(),
        "base_url": data.get("base_url", "").strip() or config.LLM_DEFAULT_BASE_URL,
        "model": data.get("model", "").strip(),
    }


def get_invite(data: dict) -> str:
    """提取邀请码/链接文本，拼到话题里。"""
    code = data.get("invite_code", "").strip()
    link = data.get("invite_link", "").strip()
    parts = []
    if code: parts.append(f"邀请码: {code}")
    if link: parts.append(f"链接: {link}")
    return " | ".join(parts) if parts else ""


# ── 前端页面 ───────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API：设置 ─────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def api_settings():
    return jsonify({
        "today_count": get_today_count(),
        "bili_logged_in": bool(_get_bili_cookie("SESSDATA")),
    })


# ── API：LLM 模型列表 & 验证 ─────────────────────────

@app.route("/api/llm/models", methods=["POST"])
def api_llm_models():
    """
    用用户的 API Key 拉取可用模型列表。
    """
    data = request.get_json() or {}
    api_key = data.get("api_key", "").strip()
    base_url = data.get("base_url", "").strip() or config.LLM_DEFAULT_BASE_URL
    if not api_key:
        return jsonify({"error": "请先填写 API Key"}), 400
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        models = client.models.list()
        return jsonify({
            "models": sorted([m.id for m in models]),
            "total": len([m for m in models]),
        })
    except Exception as e:
        return jsonify({"error": "获取模型列表失败，请检查 API Key 和接口地址"}), 400


@app.route("/api/llm/verify", methods=["POST"])
def api_llm_verify():
    """
    验证 API Key + 模型能否正常调用。
    """
    data = request.get_json() or {}
    api_key = data.get("api_key", "").strip()
    base_url = data.get("base_url", "").strip() or config.LLM_DEFAULT_BASE_URL
    model = data.get("model", "").strip()
    if not api_key:
        return jsonify({"ok": False, "error": "请填写 API Key"})
    if not model:
        return jsonify({"ok": False, "error": "请先选择模型"})
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "回复OK"}],
            max_tokens=10,
        )
        content = resp.choices[0].message.content
        return jsonify({"ok": True, "reply": content, "model": model,
                        "tokens": resp.usage.total_tokens if resp.usage else 0})
    except Exception as e:
        return jsonify({"ok": False, "error": "验证失败，请检查 API Key 和模型"})


# ── API：B站扫码登录 ──────────────────────────────────

@app.route("/api/bili/qrcode/generate")
def bili_qrcode_generate():
    """
    生成 B站扫码登录二维码。
    返回 qrcode_key + url（前端用 url 生成二维码图片）。
    """
    try:
        resp = req.get(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
            headers=_BILI_HEADERS, timeout=10
        )
        data = resp.json()
        if data.get("code") != 0:
            return jsonify({"error": "生成二维码失败"}), 500
        session["bili_qr_key"] = data["data"]["qrcode_key"]
        session.modified = True
        return jsonify({
            "qrcode_key": data["data"]["qrcode_key"],
            "url": data["data"]["url"],
        })
    except Exception as e:
        warning("app", f"生成二维码异常: {e}")
        return jsonify({"error": "生成二维码失败，请检查网络"}), 500


@app.route("/api/bili/qrcode/poll")
def bili_qrcode_poll():
    """
    轮询扫码状态。
    返回: {status: "waiting|scanned|confirmed|error", uname?}
    成功后自动将 Cookie 存入 session。
    """
    key = request.args.get("key", "")
    if not key:
        return jsonify({"status": "error", "message": "缺少参数"})

    try:
        resp = req.get(
            f"https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={key}",
            headers=_BILI_HEADERS, timeout=10
        )
        body = resp.json()
        if body.get("code") != 0:
            return jsonify({"status": "error", "message": body.get("message", "")})

        code = body["data"]["code"]  # 0=确认, 1=已扫码未确认, 其他=未扫码
        if code == 0:
            # 登录成功！跟着 SSO 重定向链拿到 Cookie
            sso_url = body["data"]["url"]
            s = req.Session()
            s.headers.update(_BILI_HEADERS.copy())
            s.get(sso_url, timeout=10, allow_redirects=True)
            _save_bili_session(s)

            # 获取用户名
            uname = ""
            nav = _bili_session().get("https://api.bilibili.com/x/web-interface/nav", timeout=10)
            nav_data = nav.json()
            if nav_data.get("data", {}).get("isLogin"):
                uname = nav_data["data"].get("uname", "")

            session["bili_qr_key"] = ""
            session.modified = True
            return jsonify({"status": "confirmed", "uname": uname})
        elif code == 1:
            return jsonify({"status": "scanned", "message": "已扫码，请在手机上确认"})
        else:
            return jsonify({"status": "waiting", "message": "等待扫码"})
    except Exception as e:
        warning("app", f"轮询扫码异常: {e}")
        return jsonify({"status": "error", "message": "登录失败，请重试"})


@app.route("/api/bili/logout", methods=["POST"])
def bili_logout():
    """清除 B站登录状态。"""
    session.pop("bili_cookies", None)
    session.modified = True
    return jsonify({"ok": True})


# ── API：检查 B站登录状态 ─────────────────────────────

@app.route("/api/bili/status")
def api_bili_status():
    """检查当前 session 的 B站登录状态。"""
    bili_sess = _bili_session()
    sessdata = _get_bili_cookie("SESSDATA")
    if not sessdata:
        return jsonify({"logged_in": False, "uname": ""})
    try:
        resp = bili_sess.get("https://api.bilibili.com/x/web-interface/nav", timeout=10)
        body = resp.json()
        if body.get("data", {}).get("isLogin"):
            return jsonify({
                "logged_in": True,
                "uname": body["data"].get("uname", "?"),
                "uid": body["data"].get("mid", 0),
                "level": body["data"].get("level_info", {}).get("current_level", 0),
            })
        # Cookie 过期
        session.pop("bili_cookies", None)
        session.modified = True
        return jsonify({"logged_in": False, "uname": ""})
    except Exception as e:
        return jsonify({"logged_in": False, "uname": "", "error": "状态检查失败"})


# ── API：代理发布评论 ─────────────────────────────────

@app.route("/api/bili/post-comment", methods=["POST"])
def api_post_comment():
    """
    用 session 中存储的 B站 Cookie 代理发布评论。
    无需用户手动传递 SESSDATA。
    """
    data = request.get_json() or {}
    bvid = data.get("bvid", "").strip()
    message = data.get("message", "").strip()
    if not bvid or not message:
        return jsonify({"error": "参数不全"}), 400

    sessdata = _get_bili_cookie("SESSDATA")
    csrf = _get_bili_cookie("bili_jct")
    if not sessdata or not csrf:
        return jsonify({"error": "未登录 B站", "need_login": True}), 401

    bili_sess = _bili_session()
    try:
        payload = {"oid": bvid, "type": "1", "message": message,
                   "csrf": csrf, "plat": "1"}
        resp = bili_sess.post(
            "https://api.bilibili.com/x/v2/reply/add",
            data=payload, timeout=15
        )
        body = resp.json()
        code = body.get("code", -999)
        result = {
            "success": code == 0,
            "code": code,
            "rpid": str(body.get("data", {}).get("rpid", "")) if code == 0 else "",
            "message": body.get("message", ""),
        }
        if result["success"]:
            mark_processed(bvid, "web", comment=message,
                           rpid=result["rpid"], quality=3)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "code": -999, "rpid": "",
                        "message": "发布失败，请重试"}), 500


# ── API：分析 Prompt ──────────────────────────────────

@app.route("/api/plan", methods=["POST"])
def api_plan():
    """
    用户输入一段话 → AI 分析 → 返回推广计划（关键词、卖点、引导语）。
    """
    data = request.get_json() or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "请输入推广描述"}), 400
    lp = _llm_params(data)
    plan = analyze_prompt(prompt, api_key=lp["api_key"],
                          base_url=lp["base_url"], model=lp["model"])
    if plan is None:
        return jsonify({"error": "分析失败，请检查 API Key 和模型"}), 500
    invite = get_invite(data)
    if invite:
        plan["call_to_action"] = (plan.get("call_to_action", "") + " " + invite).strip()
    return jsonify(plan)


# ── API：执行推广计划 ──────────────────────────────────

@app.route("/api/run-plan", methods=["POST"])
def api_run_plan():
    """
    接收 plan（关键词列表 + 邀请码等）→ 全流程跑 → 返回生成结果。
    """
    data = request.get_json() or {}
    keywords = data.get("keywords", [])
    invite_code = data.get("call_to_action", "")
    max_videos = int(data.get("max_videos", 3))

    if not keywords:
        return jsonify({"error": "缺少关键词"}), 400

    all_results = []
    for kw in keywords[:5]:  # 最多处理 5 个关键词
        videos = search_videos(kw)
        if not videos:
            continue
        for v in videos[:max_videos]:
            bvid = v["bvid"]
            if has_processed(bvid):
                continue
            ctx = extract_context(bvid)
            if ctx is None:
                continue
            # 话题带上邀请码信息
            topic = kw
            if invite_code:
                topic = f"{kw} - {invite_code}"
            lp = _llm_params(data)
            gen = generate_comment(ctx, topic, style_prompt=data.get("style_prompt", ""),
                                   api_key=lp["api_key"], base_url=lp["base_url"], model=lp["model"])
            if gen is None:
                continue
            all_results.append({
                "bvid": bvid,
                "url": v.get("url", f"https://www.bilibili.com/video/{bvid}"),
                "title": v["title"],
                "author": v.get("author", ""),
                "comment": gen["comment"],
                "quality": gen["quality"],
                "style": gen.get("style", ""),
                "keyword": kw,
                "status": "ready",
            })
    return jsonify({"results": all_results, "total": len(all_results)})


# ── API：搜索 ──────────────────────────────────────────

@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json() or {}
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "请输入关键词"}), 400
    page = int(data.get("page", 1))
    order = data.get("order", config.SEARCH_ORDER)
    videos = search_videos(keyword, page=page, order=order)
    return jsonify({"keyword": keyword, "videos": videos, "total": len(videos)})


# ── API：生成评论（增强版，支持邀请码）─────────────────

@app.route("/api/generate", methods=["POST"])
def api_generate():
    try:
        data = request.get_json() or {}
        bvid = data.get("bvid", "").strip()
        topic = data.get("topic", "").strip()
        invite = get_invite(data)
        if not bvid:
            return jsonify({"error": "缺少 bvid"}), 400
        ctx = extract_context(bvid)
        if ctx is None:
            return jsonify({"error": "无法获取视频信息"}), 404
        full_topic = topic or bvid
        if invite:
            full_topic = f"{full_topic} ({invite})"
        lp = _llm_params(data)
        result = generate_comment(ctx, full_topic, style_prompt=data.get("style_prompt", ""),
                                  context_aware=data.get("context_aware", True),
                                  api_key=lp["api_key"], base_url=lp["base_url"], model=lp["model"])
        if result is None:
            return jsonify({"error": "LLM 生成失败"}), 500
        result["bvid"] = bvid
        result["video_title"] = ctx["video"].get("title", "")
        return jsonify(result)
    except Exception as e:
        error("app", f"api_generate 异常: {e}")
        return jsonify({"error": "生成失败"}), 500


@app.route("/api/batch", methods=["POST"])
def api_batch():
    try:
        data = request.get_json() or {}
        keyword = data.get("keyword", "").strip()
        invite = get_invite(data)
        style_prompt = data.get("style_prompt", "")
        context_aware = data.get("context_aware", True)
        if not keyword:
            return jsonify({"error": "请输入关键词"}), 400
        max_videos = int(data.get("max_videos", config.SEARCH_PAGE_SIZE))

        videos = search_videos(keyword)
        if not videos:
            return jsonify({"keyword": keyword, "results": [], "message": "无搜索结果"})

        lp = _llm_params(data)

        # 非上下文模式：先对第一个视频生成一条标准评论，所有视频共用
        if not context_aware:
            first_ctx = extract_context(videos[0]["bvid"])
            template_comment = ""
            if first_ctx:
                gen = generate_comment(first_ctx, invite if invite else keyword,
                                       style_prompt=style_prompt, context_aware=False,
                                       api_key=lp["api_key"], base_url=lp["base_url"], model=lp["model"])
                if gen:
                    template_comment = gen["comment"]
            # 所有视频都用这条评论
            results = []
            for v in videos[:max_videos]:
                bvid = v["bvid"]
                if has_processed(bvid):
                    pt = get_processed_time(bvid); reason = f"已评论 ({pt})" if pt else "已评论"; results.append({"bvid": bvid, "title": v["title"], "status": "skipped", "reason": reason})
                    continue
                if not template_comment:
                    results.append({"bvid": bvid, "title": v["title"], "status": "skipped", "reason": "评论生成失败"})
                    continue
                results.append({
                    "bvid": bvid, "url": v.get("url", f"https://www.bilibili.com/video/{bvid}"),
                    "title": v["title"], "author": v.get("author", ""),
                    "comment": template_comment, "quality": 3,
                    "style": "统一", "status": "ready",
                })
            return jsonify({"keyword": keyword, "results": results, "total": len(results)})

        # 上下文模式：每个视频单独生成
        results = []
        for i, v in enumerate(videos[:max_videos]):
            bvid = v["bvid"]
            if has_processed(bvid):
                pt = get_processed_time(bvid); reason = f"已评论 ({pt})" if pt else "已评论"; results.append({"bvid": bvid, "title": v["title"], "status": "skipped", "reason": reason})
                continue
            ctx = extract_context(bvid)
            if ctx is None:
                results.append({"bvid": bvid, "title": v["title"], "status": "skipped", "reason": "无法提取上下文"})
                continue
            full_topic = invite if invite else keyword
            gen = generate_comment(ctx, full_topic, style_prompt=style_prompt, context_aware=context_aware,
                                   api_key=lp["api_key"], base_url=lp["base_url"], model=lp["model"])
            if gen is None:
                results.append({"bvid": bvid, "title": v["title"], "status": "skipped", "reason": "LLM 生成失败"})
                continue
            results.append({
                "bvid": bvid, "url": v.get("url", f"https://www.bilibili.com/video/{bvid}"),
                "title": v["title"], "author": v.get("author", ""),
                "comment": gen["comment"], "quality": gen["quality"],
                "style": gen.get("style", ""),
                "has_subtitle": ctx.get("has_subtitle", False),
                "subtitle_preview": (ctx.get("subtitle") or "")[:100] if ctx.get("subtitle") else "",
                "status": "ready",
            })
        return jsonify({"keyword": keyword, "results": results, "total": len(results)})
    except Exception as e:
        error("app", f"api_batch 异常: {e}")
        return jsonify({"error": "批量处理失败"}), 500

@app.route("/api/history")
def api_history():
    """返回已处理的视频历史。"""
    limit = request.args.get("limit", 20, type=int)
    records = get_history(limit=min(limit, 100))
    return jsonify({"records": records, "total": len(records)})


# ── API：统计 ──────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


# ── API：标记已处理 ────────────────────────────────────

@app.route("/api/mark", methods=["POST"])
def api_mark():
    data = request.get_json() or {}
    bvid = data.get("bvid", "")
    topic = data.get("topic", "")
    comment = data.get("comment", "")
    rpid = data.get("rpid", "")
    quality = int(data.get("quality", 0))
    if bvid and topic:
        mark_processed(bvid, topic, comment=comment, rpid=rpid, quality=quality)
        return jsonify({"ok": True})
    return jsonify({"error": "参数不全"}), 400


if __name__ == "__main__":
    info("app", f"启动服务器 http://127.0.0.1:5000")
    debug_mode = os.getenv("FLASK_DEBUG", "").lower() == "true"
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
