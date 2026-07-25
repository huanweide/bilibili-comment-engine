"""
全局配置管理。
服务器不预设任何 API Key，由用户在前端自行填写。
"""

import os

# ── B站 Cookie（后备，主登录方式是前端扫码，存 Flask session）──
BILI_SESSDATA = ""
BILI_CSRF = ""
BILI_DEDEUSERID = ""

# ── 搜索配置 ───────────────────────────────────────────
SEARCH_PAGE_SIZE = 10       # 每次搜索取几个视频
SEARCH_ORDER = "click"      # click / pubdate / stow

# ── 速率与风控 ─────────────────────────────────────────
POST_DELAY_SECONDS = 8      # 发评论间隔（B站反刷屏 ~6s，留余量）
MAX_POSTS_PER_HOUR = 30     # 每小时最多发几条
MAX_DAILY_POSTS = 100       # 每天最多发几条
RETRY_DELAY_SECONDS = 30    # 被限流后等多久重试
MAX_CONSECUTIVE_FAILS = 3   # 连续失败几次暂停

# ── LLM 默认参数（用户可在前端覆盖）────────────────────
LLM_MAX_TOKENS = 500        # 生成的评论最长多少 token（含 reasoning 消耗）
LLM_TEMPERATURE = 0.85      # 生成温度（偏高保证多样性）
LLM_TOP_P = 0.92
LLM_DEFAULT_BASE_URL = "https://api.deepseek.com"

# ── 上下文提取 ─────────────────────────────────────────
SUBTITLE_MAX_CHARS = 3000   # 字幕最长截断（控制 prompt 长度）
HOT_COMMENT_COUNT = 5       # 提取几条热评做上下文

# ── 运行模式 ───────────────────────────────────────────
DRY_RUN = False             # True = 只搜索+生成，不实际发评论
LOG_LEVEL = "INFO"          # DEBUG / INFO / WARNING / ERROR

# ── 数据库 ─────────────────────────────────────────────
DB_PATH = "data/processed.db"
