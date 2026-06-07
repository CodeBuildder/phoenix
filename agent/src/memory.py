"""
Phoenix Agent — predictive-healing memory store  (#6)
Copyright (c) 2026 Kaushikkumaran

SQLite-backed store of { fault_type, taxonomy_category, target_namespace,
action_taken, outcome, mttr_seconds, diagnosis, timestamp } records.

Retrieval surfaces "seen this N times, action A worked M/N, confidence X%"
to the diagnose and heal_plan nodes so the agent can reason with history
instead of guessing from scratch every time.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    fault_type         TEXT NOT NULL,
                    taxonomy_category  TEXT,
                    target_namespace   TEXT,
                    action_taken       TEXT NOT NULL,
                    outcome            TEXT NOT NULL,
                    mttr_seconds       REAL,
                    diagnosis          TEXT,
                    timestamp          TEXT NOT NULL
                )
            """)
            conn.commit()

    def record(
        self,
        *,
        fault_type: str,
        taxonomy_category: str | None,
        target_namespace: str | None,
        action_taken: str,
        outcome: str,
        mttr_seconds: float | None,
        diagnosis: str | None,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO memory
                      (fault_type, taxonomy_category, target_namespace,
                       action_taken, outcome, mttr_seconds, diagnosis, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fault_type, taxonomy_category, target_namespace,
                        action_taken, outcome, mttr_seconds, diagnosis, _now(),
                    ),
                )
                conn.commit()

    def recall(self, fault_type: str) -> str:
        """
        Returns a human-readable summary for the diagnose prompt:
        "seen this N times, action A worked M/N, confidence X%"
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT action_taken, outcome, mttr_seconds
                FROM memory
                WHERE fault_type = ?
                ORDER BY timestamp DESC
                LIMIT 20
                """,
                (fault_type,),
            ).fetchall()

        if not rows:
            return f"No prior incidents with fault_type='{fault_type}' in memory."

        total = len(rows)
        successes = sum(1 for r in rows if r["outcome"] == "success")

        # Per-action breakdown
        action_stats: dict[str, dict[str, int]] = {}
        for r in rows:
            a = r["action_taken"]
            action_stats.setdefault(a, {"success": 0, "failed": 0})
            action_stats[a][r["outcome"]] += 1

        mttr_vals = [r["mttr_seconds"] for r in rows if r["mttr_seconds"] is not None]
        avg_mttr = sum(mttr_vals) / len(mttr_vals) if mttr_vals else None

        lines = [
            f"Prior incidents for fault_type='{fault_type}': {total} total, "
            f"{successes}/{total} resolved successfully."
        ]
        for action, counts in action_stats.items():
            total_a = counts["success"] + counts["failed"]
            conf = int(counts["success"] / total_a * 100)
            lines.append(
                f"  Action '{action}': {counts['success']}/{total_a} success "
                f"(confidence {conf}%)"
            )
        if avg_mttr is not None:
            lines.append(f"  Avg MTTR: {avg_mttr:.0f}s")

        return "\n".join(lines)

    def list_all(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory ORDER BY timestamp DESC"
            ).fetchall()
        return [dict(r) for r in rows]
