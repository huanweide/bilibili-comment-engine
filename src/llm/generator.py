"""
LLM 评论生成器。
内置 Prompt 模板池 + 单次调用多输出（评论 + 质量分 + 风格标签）。
接受用户提供的 API Key / Base URL / Model，不依赖全局配置。
"""

import json
import re

from openai import OpenAI

import config
from src.context.assembler import assemble_prompt
from src.logger import debug, warning, error


def _make_client(api_key: str = "", base_url: str = "") -> OpenAI:
    """创建 OpenAI 客户端，不依赖全局配置。"""
    return OpenAI(
        api_key=api_key or "sk-placeholder",
        base_url=base_url or config.LLM_DEFAULT_BASE_URL,
    )


def generate_comment(ctx: dict, topic: str, retry_count: int = 0,
                     style_prompt: str = "", context_aware: bool = True,
                     api_key: str = "", base_url: str = "",
                     model: str = "") -> dict | None:
    """
    生成一条评论。

    参数:
        ctx: extract_context() 返回的上下文
        topic: 推广话题
        retry_count: 内部重试计数器
        style_prompt: 用户自定义评论风格描述
        context_aware: 是否根据视频内容生成差异化评论
        api_key/base_url/model: 用户提供的 LLM 配置

    返回:
        字典含 comment, quality, style, topic, tokens_used
    """
    system, user = assemble_prompt(ctx, topic, style_prompt=style_prompt, context_aware=context_aware)
    bvid = ctx["bvid"]
    video_title = ctx["video"]["title"]

    debug("llm", f"生成评论 [{bvid}] 话题={topic} 标题={video_title[:30]}...")

    try:
        client = _make_client(api_key, base_url)
        actual_model = model or "deepseek-chat"

        resp = client.chat.completions.create(
            model=actual_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
            top_p=config.LLM_TOP_P,
        )

        raw = resp.choices[0].message.content.strip()
        tokens = resp.usage.total_tokens if resp.usage else 0

        parsed = _parse_llm_json(raw)

        if parsed is None:
            warning("llm", f"JSON 解析失败 [{bvid}]，降级为纯文本: {raw[:50]}...")
            parsed = {"comment": raw, "quality": 3, "style": "未知"}

        quality = int(parsed.get("quality", 3))
        comment = parsed.get("comment", raw).strip()

        if quality < 3 and retry_count < 2:
            debug("llm", f"质量评分 {quality} < 3，重试 [{bvid}] (第{retry_count+1}次)")
            return generate_comment(ctx, topic, retry_count + 1, style_prompt,
                                    context_aware, api_key, base_url, model)

        if quality < 3:
            warning("llm", f"重试 {retry_count} 次后质量仍低 ({quality}) [{bvid}]，但仍返回")

        debug("llm", f"[OK] 评论生成 [{bvid}] 质量={quality} 风格={parsed.get('style', '?')} tokens={tokens}")

        return {
            "comment": comment,
            "quality": quality,
            "style": parsed.get("style", "未知"),
            "topic": topic,
            "tokens_used": tokens,
        }

    except Exception as e:
        error("llm", f"LLM 调用异常 [{bvid}]: {e}")
        if retry_count < 1:
            return generate_comment(ctx, topic, retry_count + 1, style_prompt,
                                    context_aware, api_key, base_url, model)
        return None


def _parse_llm_json(raw: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象。兼容 markdown 代码块包裹和双层括号。"""
    cleaned = raw.strip()
    # 去掉 ```json ... ``` 包裹
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)
    cleaned = cleaned.strip()
    # 处理双层括号 {{...}}
    if cleaned.startswith('{{') and cleaned.endswith('}}'):
        cleaned = cleaned[1:-1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试找第一个完整的 { ... } 对（处理嵌套括号）
        depth = 0
        start = -1
        for i, ch in enumerate(cleaned):
            if ch == '{':
                if start == -1:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    try:
                        return json.loads(cleaned[start:i+1])
                    except json.JSONDecodeError:
                        start = -1  # 继续找下一个顶层对象
    return None
