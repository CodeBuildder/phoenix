"""Restart-safe SQLite repository for Phoenix chaos scenarios."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3

from config import config
from models import Scenario, ScenarioStatus


class ScenarioStore:
    """Persist the complete canonical Scenario document behind the existing async API."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._lock = asyncio.Lock()
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                document TEXT NOT NULL
            )
        """)
        self._connection.commit()

    async def put(self, scenario: Scenario) -> Scenario:
        document = scenario.model_dump_json()
        async with self._lock:
            self._connection.execute(
                """INSERT INTO scenarios (id, status, created_at, updated_at, document)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                     updated_at=CURRENT_TIMESTAMP, document=excluded.document""",
                (scenario.id, scenario.status.value, scenario.created_at, document),
            )
            self._connection.commit()
        return scenario

    async def get(self, scenario_id: str) -> Scenario | None:
        row = self._connection.execute(
            "SELECT document FROM scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
        return Scenario.model_validate_json(row["document"]) if row else None

    async def list(self, status: ScenarioStatus | None = None) -> list[Scenario]:
        if status is None:
            rows = self._connection.execute(
                "SELECT document FROM scenarios ORDER BY created_at"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT document FROM scenarios WHERE status = ? ORDER BY created_at",
                (status.value,),
            ).fetchall()
        scenarios: list[Scenario] = []
        for row in rows:
            try:
                scenarios.append(Scenario.model_validate_json(row["document"]))
            except (ValueError, json.JSONDecodeError):
                continue
        return scenarios

    async def remove(self, scenario_id: str) -> None:
        async with self._lock:
            self._connection.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
            self._connection.commit()

    async def clear(self) -> None:
        async with self._lock:
            self._connection.execute("DELETE FROM scenarios")
            self._connection.commit()

    def close(self) -> None:
        self._connection.close()


store = ScenarioStore(config.DB_PATH)
