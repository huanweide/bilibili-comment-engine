# B站 LLM 上下文感知主动评论引擎 — 架构文档

## 一句话定位

自动搜索 B站目标领域视频 → 提取标题/字幕/热评理解视频内容 → LLM 生成"真看过视频的人才会写的"评论 → 主动发布。跟已有 AI 评论机器人的核心区别：**主动出击，而非被动回复**。

## 系统架构

```
┌──────────────────────────────────────────────────┐
│                    CLI 层                         │
│  main.py — argparse 入口                         │
│  --keyword / --batch / --dry-run / --daemon       │
├──────────────────────────────────────────────────┤
│                  编排层                           │
│  orchestrator.py — Pipeline 主循环               │
│  搜索 → 提取 → 生成 → 发布 → 记录                 │
│  错误处理：单视频失败→skip，连续3次→暂停           │
├────────────────┬────────────────┬────────────────┤
│   B站 API 层   │   上下文层      │    LLM 层      │
│                │                │                │
│  client.py     │  extractor.py  │  generator.py  │
│  会话+Cookie   │  上下文提取     │  评论生成       │
│                │                │  (含模板池)     │
│  search.py     │  assembler.py  │                │
│  视频搜索       │  Prompt组装    │  硅基流动       │
│                │                │  DeepSeek V4    │
│  video.py      │                │                │
│  视频元数据     │                │                │
│                │                │                │
│  subtitle.py   │                │                │
│  CC字幕提取     │                │                │
│                │                │                │
│  comment.py    │                │                │
│  评论读取+发布  │                │                │
├────────────────┴────────────────┴────────────────┤
│                  数据层                           │
│  dedup.py — SQLite 去重 (bvid+topic 联合主键)     │
│  risk.py  — 风控管理 (速率/配额/自适应降速)        │
│  logger.py — 结构化日志                           │
└──────────────────────────────────────────────────┘
```

## 核心模块

### B站 API 层 (`src/bilibili/`)

| 模块 | 职责 | 关键 API |
|------|------|---------|
| `client.py` | HTTP 会话管理、Cookie 注入、CSRF 提取、过期检测 | 全部接口共用 |
| `search.py` | 按关键词搜索视频 → BV 号列表 | `x/web-interface/search/type` |
| `video.py` | 获取视频标题/标签/简介/播放量/UP主 | `x/web-interface/view` |
| `subtitle.py` | CC 字幕提取（MVP 不做 ASR） | `x/player/v2` + 字幕 JSON |
| `comment.py` | 热门评论读取 + 评论发布（含反刷屏变体） | `x/v2/reply/main` + `x/v2/reply/add` |

### 上下文层 (`src/context/`)

- **extractor.py**：聚合 video + subtitle + comments → 结构化上下文字典
- **assembler.py**：上下文字典 → System Prompt + User Prompt（两段式）

### LLM 层 (`src/llm/`)

- **generator.py**：
  - 对接硅基流动 DeepSeek V4 Pro
  - 单次调用输出：评论正文 + 质量自评(1-5) + 风格标签
  - 质量 < 3 自动重生成（最多 2 次）
  - 模板作为模块级常量内置

### 编排层

- **orchestrator.py**：串联完整 Pipeline，单视频失败不中断整体
- **dedup.py**：SQLite 持久化去重，`(bvid, topic)` 联合主键
- **risk.py**：速率自适应、连续失败熔断、每日/每小时配额

## 闪光点来源（从参考项目学到的）

| 闪光点 | 来源 | 落地方式 |
|--------|------|---------|
| 单次 LLM 调用多输出 | bilibili-ai-bot | `generator.py` 一次输出评论+质量+风格 |
| Cookie 过期检测 | bilibili-ai-bot | `client.py` 拦截 -101 错误码 |
| 反刷屏变体池 | promo skill 实战验证 | `comment.py` 前缀+后缀+随机 emoji |
| SQLite 替代 JSON | 自研改进 | 两个参考项目都用 JSON，我们换 SQLite（并发安全+查重更快） |
| 速率自适应 | bilibili_learning_bot throttle | `risk.py` 遇 12019 自动翻倍间隔 |
| Mixin 不采用 | bilibili_learning_bot | 判定过重，保持单体 orchestrator |

## 技术选型理由

| 选择 | 为什么不选别的 |
|------|---------------|
| Python | JS 生态的 B站 API 库不如 Python 成熟；我们团队主力语言 |
| 硅基流动 DeepSeek V4 Pro | 便宜（¥1/M tokens），中文理解强过 GPT-4o，OpenAI 兼容协议零迁移成本 |
| SQLite | 零部署、零配置、并发安全。MySQL/PostgreSQL 对这个量级是过度设计 |
| 单体架构 | 不超过 1000 行的项目拆分微服务是自嗨。未来真需要扩展再拆 |

## 实现路线图

### Phase 1 — MVP（验证核心假设）
- [x] 项目骨架搭建（20 个文件）
- [ ] 环境配置：环境变量 + Cookie 获取
- [ ] 干跑测试：`python main.py --keyword DeepSeek --dry-run`
- [ ] 单关键词实测：挑一个小号试发 3-5 条
- [ ] **验证假设**：B站对主动评论的风控力度

### Phase 2 — 扩展
- [ ] ASR fallback（SenseVoiceSmall 音频→文字）
- [ ] 多话题模板自动切换（根据视频内容自动选最匹配的话题）
- [ ] Web 管理面板（Flask，实时看进度+统计）

### Phase 3 — 规模化
- [ ] 守护模式长稳运行（7×24）
- [ ] 向量记忆：记住自己发过的评论风格，避免"自我重复"感
- [ ] 效果量化：评论点赞数追踪 → 哪些话题/风格效果好

## 风险对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| B站阿瓦隆检测 AI 评论模式 | 中 | 封号 | 速率自适应+变体池+干跑验证 |
| Cookie SESSDATA 过期 | 高 | 停摆 | RSA refresh_token 续期（Phase 2） |
| LLM 生成垃圾评论 | 高 | 浪费配额+被举报 | 质量自评 < 3 重生成 + 干跑人工抽查 |
| DeepSeek API 波动 | 低 | 中断 | 配置备用 API（Phase 2） |
| 字幕提取率低（很多视频无 CC） | 中 | 评论质量下降 | Phase 2 ASR fallback |

## 参考项目

| 项目 | 学到了什么 | 借鉴程度 |
|------|-----------|---------|
| bilibili-ai-bot | 单函数多输出、好感度系统、密码保护面板 | 仅参考思路 |
| bilibili_learning_bot | Mixin 组合模式（不采用）、知识库分类、ASR | 仅参考思路 |
| siliconflow-bilibili-promo | B站 API 实战验证、12051 反刷屏策略 | 改改就能用 |
