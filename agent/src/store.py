"""Restart-safe SQLite repository for complete Phoenix agent runs."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from models import AgentNode, AgentRun


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._lock = asyncio.Lock()
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                scenario_id TEXT PRIMARY KEY,
                node TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                document TEXT NOT NULL
            )
        """)
        self._connection.commit()

    async def put(self, run: AgentRun) -> AgentRun:
        run.updated_at = _now()
        document = run.model_dump_json()
        async with self._lock:
            self._connection.execute(
                """INSERT INTO agent_runs (scenario_id, node, started_at, updated_at, document)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(scenario_id) DO UPDATE SET node=excluded.node,
                     updated_at=excluded.updated_at, document=excluded.document""",
                (run.scenario_id, run.node.value, run.started_at, run.updated_at, document),
            )
            self._connection.commit()
        return run

    async def get(self, scenario_id: str) -> AgentRun | None:
        row = self._connection.execute(
            "SELECT document FROM agent_runs WHERE scenario_id = ?", (scenario_id,)
        ).fetchone()
        return AgentRun.model_validate_json(row["document"]) if row else None

    async def list(self) -> list[AgentRun]:
        rows = self._connection.execute(
            "SELECT document FROM agent_runs ORDER BY started_at DESC"
        ).fetchall()
        runs: list[AgentRun] = []
        for row in rows:
            try:
                runs.append(AgentRun.model_validate_json(row["document"]))
            except (ValueError, json.JSONDecodeError):
                continue
        return runs

    async def update(self, scenario_id: str, **kwargs: Any) -> AgentRun | None:
        async with self._lock:
            row = self._connection.execute(
                "SELECT document FROM agent_runs WHERE scenario_id = ?", (scenario_id,)
            ).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["document"])
            for key, value in kwargs.items():
                setattr(run, key, value)
            run.updated_at = _now()
            self._connection.execute(
                "UPDATE agent_runs SET node = ?, updated_at = ?, document = ? WHERE scenario_id = ?",
                (run.node.value, run.updated_at, run.model_dump_json(), scenario_id),
            )
            self._connection.commit()
        return run

    async def transition(self, scenario_id: str, node: AgentNode) -> AgentRun | None:
        return await self.update(scenario_id, node=node)

    async def has(self, scenario_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM agent_runs WHERE scenario_id = ?", (scenario_id,)
        ).fetchone()
        return row is not None

    async def reconcile_interrupted(self) -> int:
        """Fail closed after restart; retain evidence but never resume a risky action implicitly."""
        interrupted = 0
        for run in await self.list():
            if run.node in {AgentNode.DONE, AgentNode.ABORTED, AgentNode.ERROR}:
                continue
            await self.update(
                run.scenario_id,
                node=AgentNode.ERROR,
                error=f"Phoenix process restarted while run was at {run.node.value}; manual review required",
                completed_at=_now(),
            )
            interrupted += 1
        return interrupted

    async def clear(self) -> None:
        async with self._lock:
            self._connection.execute("DELETE FROM agent_runs")
            self._connection.commit()

    def close(self) -> None:
        self._connection.close()


store = RunStore()
