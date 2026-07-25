"""
Prompt 分析器。
用户输入"帮我推广硅基流动邀请码 axOmWfWi" → 提取关键词、卖点、话术方向。
"""

import json
import re
from openai import OpenAI
import config
from src.logger import debug, warning


def analyze_prompt(user_prompt: str, api_key: str = "",
                   base_url: str = "", model: str = "") -> dict | None:
    """
    分析用户的推广 prompt，返回结构化计划。

    参数:
        user_prompt: 推广描述
        api_key/base_url/model: 用户提供的 LLM 配置

    返回:
        { summary, keywords, selling_points, comment_style, call_to_action, max_videos }
    """
    system_prompt = (
        "你是一个B站推广策略分析师。用户的输入是一个推广诉求，你需要：\n"
        "1. 理解他们要推广什么\n"
        "2. 想出5-8个B站搜索关键词（覆盖目标人群可能搜的词）\n"
        "3. 提炼3-5个核心卖点\n"
        "4. 建议评论风格方向\n"
        "5. 提取引导语（邀请码/链接等）\n"
        "\n"
        "输出JSON（不要markdown代码块）：\n"
        '{\n'
        '  "summary": "一句话总结",\n'
        '  "keywords": ["关键词1", "关键词2", ...],\n'
        '  "selling_points": ["卖点1", "卖点2", ...],\n'
        '  "comment_style": "风格描述",\n'
        '  "call_to_action": "引导语",\n'
        '  "max_videos": 3\n'
        '}'
    )

    try:
        client = OpenAI(
            api_key=api_key or "sk-placeholder",
            base_url=base_url or config.LLM_DEFAULT_BASE_URL,
        )
        actual_model = model or "deepseek-chat"
        resp = client.chat.completions.create(
            model=actual_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
            temperature=0.7,
        )
        raw = resp.choices[0].message.content.strip()
        return _parse_json(raw)
    except Exception as e:
        warning("planner", f"分析 prompt 失败: {e}")
        return None


def _parse_json(raw: str) -> dict | None:
    """从 LLM 输出中提取 JSON。"""
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', raw.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)
    cleaned = cleaned.strip()
    if cleaned.startswith('{{') and cleaned.endswith('}}'):
        cleaned = cleaned[1:-1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 找第一层 { }
        depth, start = 0, -1
        for i, ch in enumerate(cleaned):
            if ch == '{':
                if start == -1: start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    try:
                        return json.loads(cleaned[start:i+1])
                    except:
                        start = -1
    return None
