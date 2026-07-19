import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models import AgentNode, AgentRun, ApprovalStatus, DiagnosisResult
from store import RunStore


@pytest.mark.asyncio
async def test_complete_agent_run_survives_restart(tmp_path):
    path = tmp_path / "agent.db"
    first = RunStore(str(path))
    run = AgentRun(
        scenario_id="scn-restart",
        scenario={"id": "scn-restart", "correlation_id": "case-1", "domain": "chaos_mesh"},
        diagnosis=DiagnosisResult(causal_chain="pod killed", recommended_action="restart_deployment", action_target="api", risk="high", rationale="restore service"),
        approval_status=ApprovalStatus.APPROVED,
        action_result="deployment restarted",
        verify_result="two replicas ready",
        node=AgentNode.DONE,
        completed_at="2026-07-19T00:00:07Z",
        mttr_seconds=7.0,
    )
    await first.put(run)
    first.close()

    second = RunStore(str(path))
    restored = await second.get(run.scenario_id)
    assert restored is not None
    assert restored.scenario["correlation_id"] == "case-1"
    assert restored.approval_status == ApprovalStatus.APPROVED
    assert restored.verify_result == "two replicas ready"
    assert restored.mttr_seconds == 7.0
    second.close()


@pytest.mark.asyncio
async def test_approval_and_transition_updates_survive_restart(tmp_path):
    path = tmp_path / "agent.db"
    store = RunStore(str(path))
    await store.put(AgentRun(scenario_id="scn-gated", approval_status=ApprovalStatus.PENDING))
    await store.update("scn-gated", approval_status=ApprovalStatus.APPROVED)
    await store.transition("scn-gated", AgentNode.EXECUTE)
    store.close()

    reopened = RunStore(str(path))
    restored = await reopened.get("scn-gated")
    assert restored.approval_status == ApprovalStatus.APPROVED
    assert restored.node == AgentNode.EXECUTE
    assert await reopened.has("scn-gated") is True
    reopened.close()


@pytest.mark.asyncio
async def test_corrupt_run_is_skipped_from_history(tmp_path):
    path = tmp_path / "agent.db"
    store = RunStore(str(path))
    store._connection.execute(
        "INSERT INTO agent_runs (scenario_id,node,started_at,updated_at,document) VALUES (?,?,?,?,?)",
        ("broken", "error", "2026-07-19T00:00:00Z", "2026-07-19T00:00:00Z", "not-json"),
    )
    store._connection.commit()
    assert await store.list() == []
    store.close()


@pytest.mark.asyncio
async def test_restart_fails_incomplete_action_closed_without_losing_history(tmp_path):
    path = tmp_path / "agent.db"
    first = RunStore(str(path))
    await first.put(AgentRun(scenario_id="scn-interrupted", node=AgentNode.EXECUTE, approval_status=ApprovalStatus.APPROVED))
    first.close()

    second = RunStore(str(path))
    assert await second.reconcile_interrupted() == 1
    restored = await second.get("scn-interrupted")
    assert restored.node == AgentNode.ERROR
    assert restored.approval_status == ApprovalStatus.APPROVED
    assert "manual review required" in restored.error
    assert restored.completed_at is not None
    second.close()
