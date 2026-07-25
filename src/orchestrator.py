"""
主编排器。
串联搜索 → 上下文提取 → LLM 生成 → 评论发布 → 去重记录 的完整 Pipeline。
内置错误处理：单视频失败→跳过+日志，连续3次失败→暂停。
"""

import random

import config
from src.bilibili.search import search_videos
from src.bilibili.comment import post_comment, classify_error
from src.context.extractor import extract_context
from src.llm.generator import generate_comment
from src.dedup import has_processed, mark_processed
from src.risk import RiskManager
from src.logger import info, warning, error


def orchestrate(keyword: str, max_videos: int = None) -> list[dict]:
    """
    对单个关键词执行完整推广流程。

    参数:
        keyword: 搜索关键词
        max_videos: 最多处理几个视频（None = 按配置的量）

    返回:
        [
            {
                "bvid": "BVxxx",
                "url": "https://...",
                "video_title": "...",
                "comment": "发出的评论",
                "quality": 3,
                "style": "认真讨论",
                "rpid": "评论ID",
                "success": True,
            },
            ...
        ]
    """
    if max_videos is None:
        max_videos = config.SEARCH_PAGE_SIZE

    risk = RiskManager()
    results = []
    skipped = 0

    info("orchestrator", f"═══ 开始推广 [{keyword}] ═══")

    # 1. 搜索视频
    videos = search_videos(keyword, order=config.SEARCH_ORDER)
    if not videos:
        warning("orchestrator", f"关键词 [{keyword}] 无搜索结果")
        return results

    info("orchestrator", f"搜索到 {len(videos)} 个视频，计划处理 {min(max_videos, len(videos))} 个")

    for i, video in enumerate(videos):
        if i >= max_videos:
            break
        if risk.is_stopped:
            warning("orchestrator", "风控触发停止，退出循环")
            break

        # 配额检查
        if not risk.check_quota():
            break

        bvid = video["bvid"]
        bvid_url = video["url"]

        # 2. 去重检查
        if has_processed(bvid):
            debug_orchestrator(f"跳过 [{bvid}]: 已处理过")
            skipped += 1
            continue

        info("orchestrator", f"[{i+1}/{min(max_videos, len(videos))}] 处理 {bvid_url} — {video['title'][:30]}...")

        # 3. 提取上下文
        ctx = extract_context(bvid)
        if ctx is None:
            warning("orchestrator", f"跳过 [{bvid}]: 无法提取上下文")
            continue

        # 4. LLM 生成评论
        gen_result = generate_comment(ctx, keyword)
        if gen_result is None:
            warning("orchestrator", f"跳过 [{bvid}]: LLM 生成失败")
            continue

        comment = gen_result["comment"]
        quality = gen_result["quality"]

        # 5. 发布评论
        variant_idx = random.randint(0, 7)
        post_result = post_comment(bvid, comment, variant_idx=variant_idx)

        if post_result["success"]:
            # 成功
            risk.report_success()
            rpid = post_result.get("rpid", "")
            mark_processed(bvid, keyword, comment=post_result["final_message"],
                           rpid=rpid, quality=quality)
            results.append({
                "bvid": bvid,
                "url": bvid_url,
                "video_title": video["title"],
                "comment": post_result["final_message"],
                "quality": quality,
                "style": gen_result.get("style", ""),
                "rpid": rpid,
                "success": True,
            })
            info("orchestrator", f"[OK] [{bvid}] 发布成功 rpid={rpid} 质量={quality}")

        else:
            # 失败 → 分类处理
            err_code = post_result["code"]
            risk.report_failure(err_code)
            err_type = classify_error(err_code)

            if err_type == "stop":
                error("orchestrator", f"致命错误 [{bvid}]: {post_result['error_msg']}，停止")
                break
            elif err_type == "retry":
                warning("orchestrator", f"可重试错误 [{bvid}]: {post_result['error_msg']}，继续")
            else:
                # skip: 已评论过/评论区关闭/重复 → 标记为已处理，免得下次再试
                mark_processed(bvid, keyword, comment=post_result.get("final_message", comment),
                               rpid="", quality=quality)
                warning("orchestrator", f"跳过 [{bvid}]: {post_result['error_msg']}")

    # ── 汇总 ──
    info("orchestrator", (
        f"═══ 推广 [{keyword}] 完成: "
        f"成功 {len(results)} / 跳过 {skipped} / "
        f"剩余配额 今日={config.MAX_DAILY_POSTS - risk.get_today_count()}"
    ))
    return results


def orchestrate_batch(keywords: list[str] = None) -> dict[str, list[dict]]:
    """
    批量推广多个关键词。

    参数:
        keywords: 关键词列表，None = 使用默认关键词

    返回:
        {keyword: [results], ...}
    """
    if keywords is None:
        keywords = config.DEFAULT_KEYWORDS

    all_results = {}
    for kw in keywords:
        results = orchestrate(kw)
        all_results[kw] = results
        # 检查配额，不够就停
        if len(results) == 0:
            continue

    # 最终汇总
    total_success = sum(len(r) for r in all_results.values())
    info("orchestrator", f"═══ 批量推广完成: 总计 {total_success} 条评论 ═══")
    return all_results


def debug_orchestrator(msg: str):
    """orchestrator 专用 debug——太长不展示细节时收口。"""
    from src.logger import debug
    debug("orchestrator", msg)
