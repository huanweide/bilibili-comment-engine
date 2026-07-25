<!-- badges -->
[![License](https://img.shields.io/github/license/huanweide/bilibili-comment-engine)](LICENSE)
[![CI](https://github.com/huanweide/bilibili-comment-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/huanweide/bilibili-comment-engine/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/huanweide/bilibili-comment-engine)](https://github.com/huanweide/bilibili-comment-engine/stargazers)
<!-- /badges -->

# Bilibili Comment Engine

> AI 驱动的 B站 评论区推广工具——搜索目标视频 → 理解视频内容 → 生成真人级评论 → 一键发布。  
> **零配置启动，扫码登录，自带 API Key。**

![screenshot](https://img.shields.io/badge/Python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

---

## 快速开始

### 1. 安装

```bash
pip install flask requests openai
```

### 2. 启动

```bash
python app.py
```

浏览器打开 [http://127.0.0.1:5000](http://127.0.0.1:5000)

### 3. 使用

1. **填 API Key** — 点"设置"，填入你自己的 DeepSeek / OpenAI / 硅基流动 API Key
2. **选模型** — 点"获取模型列表"，选一个模型，点"验证连接"
3. **登录 B站** — 点"扫码登录"，手机 B站 扫码确认
4. **加关键词** — 输入想搜索的关键词，设置每个取几个视频
5. **批量生成** — 点"批量运行"，AI 自动搜索、提取、生成评论
6. **发布** — 预览评论 → 编辑修改 → 点"发布"或"发布全部"

> 不需要配置环境变量，不需要复制 Cookie，不需要命令行操作。

---

## 核心逻辑

为什么这个工具不是"固定话术刷屏机"？

1. **理解视频在讲什么** — 提取 CC 字幕 + 热门评论 + 视频标签，让 AI 知道这个视频的具体内容
2. **生成"真看过"的评论** — 每条评论基于视频上下文生成，不是"说得真好"的废话
3. **用户风格最高优先** — 你的风格要求是最高指令，AI 不会擅自修改

---

## 架构

```
┌── 用户浏览器 ────────────────────────────┐
│  localStorage: API Key / 模型 / Base URL │
│  → 每次请求自动带上 X-* 头               │
│                                           │
│  Web UI (HTML/CSS/JS, 单页 SPA)          │
│  - B站扫码登录 (QR码)                     │
│  - 关键词 + 数量管理                      │
│  - 评论生成 / 编辑 / 发布                 │
└────────────┬──────────────────────────────┘
             │ HTTP (同源，无 CORS)
┌────────────┴──────────────────────────────┐
│  Flask 服务器 (localhost:5000)             │
│                                           │
│  ┌─ 代理层 ───────────────────────────┐   │
│  │  /api/bili/qrcode/*  → B站扫码登录  │   │
│  │  /api/bili/status    → 登录状态     │   │
│  │  /api/bili/post-comment → 发评论    │   │
│  └────────────────────────────────────┘   │
│                                           │
│  ┌─ LLM 层 ───────────────────────────┐   │
│  │  /api/llm/models  → 获取模型列表   │   │
│  │  /api/llm/verify  → 验证连接       │   │
│  │  /api/generate    → 生成评论       │   │
│  │  /api/batch       → 批量全流程     │   │
│  └────────────────────────────────────┘   │
│                                           │
│  ┌─ 其他 ─────────────────────────────┐   │
│  │  /api/search      → B站搜索代理    │   │
│  │  /api/history     → 历史记录       │   │
│  │  /api/mark        → 去重标记       │   │
│  └────────────────────────────────────┘   │
└───────────────────────────────────────────┘
```

**关键设计**：
- 所有 B站 API 调用经 Flask 后端代理，不存在 CORS 问题
- B站登录通过官方扫码流程，无需手动复制 Cookie
- API Key 只存在用户的浏览器 localStorage 中，服务器不记录
- 兼容所有 OpenAI 格式的 API（DeepSeek、硅基流动、OpenAI 等）

---

## 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 后端 | Python Flask | 轻量、Python 生态好、部署简单 |
| 前端 | 原生 HTML/CSS/JS | 零依赖、开箱即用 |
| LLM | 用户自选 | 填什么 Key 就用什么，不限制 |
| B站认证 | 扫码登录 | 官方流程，安全无感 |
| 存储 | SQLite | 零运维、零部署 |

---

## 项目结构

```
bilibili-comment-engine/
├── app.py                    # Flask 服务器 + 全部 API 路由
├── config.py                 # 全局配置（无密钥）
├── requirements.txt          # Python 依赖
├── .gitignore
├── README.md
├── ARCHITECTURE.md
├── templates/
│   └── index.html            # 前端单页 (含全部 CSS + JS)
└── src/
    ├── bilibili/             # B站 API 封装层
    │   ├── client.py         # HTTP 客户端
    │   ├── search.py         # 视频搜索
    │   ├── video.py          # 视频元数据
    │   ├── subtitle.py       # CC 字幕提取
    │   └── comment.py        # 评论读取+发布
    ├── context/
    │   ├── extractor.py      # 上下文提取
    │   └── assembler.py      # Prompt 组装
    ├── llm/
    │   ├── generator.py      # LLM 评论生成
    │   └── planner.py        # Prompt 分析
    ├── dedup.py              # SQLite 去重
    ├── risk.py               # 风控管理
    ├── orchestrator.py       # 主编排器
    └── logger.py             # 日志
```

---

## 常见问题

**评论发不出去？**
先扫码登录 B站。页面顶部会显示你的用户名。如果显示"未登录"，点"扫码登录"。

**B站返回 12051？**
说明同样或相似的评论刚发过。换个关键词或修改一下评论内容。

**搜索不到视频？**
B站搜索 API 有频率限制，不要短时间内反复搜同一个关键词。

**怎么换模型？**
点"设置"→"获取模型列表"→选一个→"验证连接"。支持 DeepSeek、硅基流动、OpenAI 等。

**API Key 安全吗？**
存在你自己的浏览器 localStorage 里，不经过服务器日志，不提交到 GitHub。

**不想发评论只想看效果？**
生成的评论会先展示出来让你预览。只有点了"发布"才会真发。

---

## License

MIT
