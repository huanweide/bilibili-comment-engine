"""
SQLite 去重追踪。
持久化记录已处理过的视频，防止重复评论。
"""

import sqlite3
import os
import time

import config
from src.logger import debug


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接，自动建表。"""
    db_dir = os.path.dirname(config.DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_videos (
            bvid       TEXT NOT NULL,
            topic      TEXT NOT NULL,
            comment    TEXT,
            rpid       TEXT,
            quality    INTEGER DEFAULT 0,
            posted_at  TEXT NOT NULL,
            PRIMARY KEY (bvid, topic)
        )
    """)
    conn.commit()
    return conn


def get_processed_time(bvid: str) -> str | None:
    """如果视频已处理，返回处理时间，否则返回 None。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT posted_at FROM processed_videos WHERE bvid=? LIMIT 1", (bvid,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def has_processed(bvid: str, topic: str = "") -> bool:
    """
    检查某个视频（+话题）是否已经处理过。
    如果 topic 为空，检查该 bvid 是否有任何记录。
    """
    conn = _get_conn()
    if topic:
        row = conn.execute(
            "SELECT 1 FROM processed_videos WHERE bvid=? AND topic=?",
            (bvid, topic),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM processed_videos WHERE bvid=?",
            (bvid,),
        ).fetchone()
    conn.close()
    return row is not None


def mark_processed(bvid: str, topic: str, comment: str = "",
                   rpid: str = "", quality: int = 0):
    """标记视频+话题为已处理。"""
    conn = _get_conn()
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    conn.execute(
        "INSERT OR REPLACE INTO processed_videos (bvid, topic, comment, rpid, quality, posted_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (bvid, topic, comment, rpid, quality, ts),
    )
    conn.commit()
    conn.close()
    debug("dedup", f"已记录 [{bvid}] 话题={topic}")


def get_stats() -> dict:
    """获取统计信息。"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM processed_videos").fetchone()[0]
    today = time.strftime("%Y-%m-%d")
    today_count = conn.execute(
        "SELECT COUNT(*) FROM processed_videos WHERE posted_at LIKE ?",
        (today + "%",),
    ).fetchone()[0]
    conn.close()
    return {"total_processed": total, "today_processed": today_count}


def get_today_count() -> int:
    """今日已发评论数。"""
    return get_stats()["today_processed"]


def get_history(limit: int = 20, offset: int = 0) -> list[dict]:
    """获取已处理的视频记录，按时间倒序。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT bvid, topic, comment, rpid, quality, posted_at "
        "FROM processed_videos ORDER BY posted_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    return [
        {
            "bvid": r[0], "topic": r[1], "comment": r[2],
            "rpid": r[3], "quality": r[4], "posted_at": r[5],
        }
        for r in rows
    ]
