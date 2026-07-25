"""
风控管理模块。
速率限制 + 连续失败检测 + 每日上限 + 自适应降速。
"""

import time
from datetime import datetime

import config
from src.logger import debug, warning


class RiskManager:
    """风控管理器，每个 orchestrator 实例持有一个。"""

    def __init__(self):
        self._last_post_time = 0.0
        self._consecutive_fails = 0
        self._hourly_posts = 0
        self._hour_start = time.time()
        self._current_delay = config.POST_DELAY_SECONDS
        self._stopped = False

    # ── 速率等待 ───────────────────────────────────────

    def wait(self):
        """发评论前调用，自动等待适当间隔。"""
        if self._stopped:
            return

        elapsed = time.time() - self._last_post_time
        if elapsed < self._current_delay:
            wait_time = self._current_delay - elapsed
            debug("risk", f"速率等待 {wait_time:.1f}s（当前间隔 {self._current_delay}s）")
            time.sleep(wait_time)
        self._last_post_time = time.time()

    # ── 错误反馈 ───────────────────────────────────────

    def report_success(self):
        """报告一次成功发布。"""
        self._consecutive_fails = 0
        self._hourly_posts += 1
        # 成功后慢慢恢复默认速率
        if self._current_delay > config.POST_DELAY_SECONDS:
            self._current_delay = max(config.POST_DELAY_SECONDS, self._current_delay - 1)
            debug("risk", f"速率恢复 → {self._current_delay}s")

    def report_failure(self, code: int):
        """报告一次发布失败，根据错误码调整策略。"""
        self._consecutive_fails += 1

        if code == 12019:  # 频率限制 → 大幅降速
            self._current_delay = min(self._current_delay * 2, 120)
            warning("risk", f"触发频率限制，间隔扩大到 {self._current_delay}s")

        elif code == 12051:  # 重复评论 → 跳过即可，不降速
            pass

        elif code in (-101, -111):  # 登录问题 → 停
            self._stopped = True
            warning("risk", "登录失效，停止发布")

        if self._consecutive_fails >= config.MAX_CONSECUTIVE_FAILS:
            self._stopped = True
            warning("risk", f"连续失败 {self._consecutive_fails} 次，自动暂停")

    # ── 配额检查 ───────────────────────────────────────

    def check_quota(self) -> bool:
        """
        检查是否还有发布配额。
        返回 True = 可以继续，False = 配额耗尽。
        """
        # 每小时重置
        if time.time() - self._hour_start > 3600:
            self._hourly_posts = 0
            self._hour_start = time.time()

        if self._hourly_posts >= config.MAX_POSTS_PER_HOUR:
            warning("risk", f"每小时上限 {config.MAX_POSTS_PER_HOUR} 条已达，等待下个小时")
            return False

        if self.get_today_count() >= config.MAX_DAILY_POSTS:
            warning("risk", f"每日上限 {config.MAX_DAILY_POSTS} 条已达")
            return False

        return True

    def get_today_count(self) -> int:
        """获取今日已发评论数（从 dedup 模块查询）。"""
        from src.dedup import get_today_count
        return get_today_count()

    @property
    def is_stopped(self) -> bool:
        return self._stopped

    @property
    def current_delay(self) -> float:
        return self._current_delay
