"""
Prompt 组装器。
将结构化上下文组装成 LLM-ready 的 system + user prompt。
"""

import config


def assemble_prompt(ctx: dict, topic: str, style_prompt: str = "", context_aware: bool = True) -> tuple[str, str]:
    """
    组装 system prompt 和 user prompt。

    参数:
        ctx: extract_context() 返回的上下文字典
        topic: 推广话题（如 "DeepSeek"、"硅基流动"）
        style_prompt: 用户自定义的评论风格描述，如"以普通用户口吻，自然地提到邀请码"
        context_aware: 是否根据视频内容生成差异化评论

    返回:
        (system_prompt, user_prompt)
    """
    video = ctx["video"]

    # ── System Prompt ────────────────────────────────────
    # 第一优先级：用户指令（必须严格遵守，不可忽略）
    user_instruction = ""
    if style_prompt:
        user_instruction = (
            "\n【最优先级 — 用户要求，必须严格遵守】\n"
            f"{style_prompt}\n"
            "你的评论必须完全符合以上要求，不可擅自改变风格和内容。"
            "用户的邀请码、链接、推广信息必须自然融入，不可丢失。\n\n"
        )
    else:
        user_instruction = (
            "\n【用户要求】写一条自然的B站评论，语气真实，不要硬广。\n\n"
        )

    # 第二优先级：上下文模式
    context_instruction = (
        "每个视频的评论必须不同，紧贴该视频的具体内容。"
        "提到视频里的具体情节、UP主的观点、弹幕槽点等。\n"
        if context_aware else
        "所有视频用同一段话术，评论内容保持一致。"
        "注意不要提到任何视频具体内容。\n"
    )

    # 第三优先级：基础规则
    system = (
        "你是B站资深用户，擅长写自然、有料、不尬的评论。\n"
        f"{user_instruction}"
        f"{context_instruction}"
        "补充规则：\n"
        "1. 语气像真人——吐槽、抖机灵、认真讨论都行\n"
        "2. 不直接推销——除非很自然地融入\n"
        "3. 长度 20-80 字\n"
        "话题：围绕「{topic}」发表看法。\n"
        "\n"
        "输出 JSON（不要 markdown 代码块）：\n"
        '{{"comment": "正文", "quality": 1-5, "style": "风格标签"}}\n'
        "quality: 1垃圾 2勉强 3合格 4不错 5绝了\n"
        "style: 吐槽/抖机灵/认真讨论/经验分享/提问"
    ).replace("{topic}", topic)

    # ── User Prompt ──
    parts = []
    parts.append(f"【视频标题】{video['title']}")

    if video.get("description"):
        desc = video["description"]
        if len(desc) > 200:
            desc = desc[:200] + "..."
        parts.append(f"【视频简介】{desc}")

    if video.get("tags"):
        parts.append(f"【标签】{'、'.join(video['tags'][:10])}")

    parts.append(f"【UP主】{video['up_name']}")
    parts.append(f"【播放量】{_format_count(video.get('play_count', 0))}")

    if ctx.get("has_subtitle"):
        sub = ctx["subtitle"]
        parts.append(f"【字幕节选】\n{sub}")

    if ctx.get("has_comments"):
        comments_str = "\n".join(
            f"- [{c['like_count']}赞] {c['content'][:80]}"
            for c in ctx["hot_comments"][:config.HOT_COMMENT_COUNT]
        )
        parts.append(f"【热门评论】\n{comments_str}")

    parts.append("\n请基于以上信息，写一条自然、跟视频内容相关的B站评论。")

    return system, "\n".join(parts)


def _format_count(n: int) -> str:
    """格式化播放量：12345 → '1.2万'"""
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)
