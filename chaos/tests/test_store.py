from datetime import datetime, timezone

import pytest

from models import Scenario, ScenarioDomain, ScenarioStatus
from store import ScenarioStore


@pytest.mark.asyncio
async def test_scenario_survives_store_restart(tmp_path):
    path = tmp_path / "chaos.db"
    first = ScenarioStore(str(path))
    scenario = Scenario(name="restart proof", domain=ScenarioDomain.SIMULATOR, fault_type="latency")
    scenario.touch_status(ScenarioStatus.RUNNING)
    scenario.correlation_id = "case-1"
    await first.put(scenario)
    first.close()

    second = ScenarioStore(str(path))
    restored = await second.get(scenario.id)
    assert restored is not None
    assert restored.model_dump() == scenario.model_dump()
    assert (await second.list(ScenarioStatus.RUNNING))[0].correlation_id == "case-1"
    second.close()


@pytest.mark.asyncio
async def test_scenario_update_and_delete_are_persistent(tmp_path):
    path = tmp_path / "chaos.db"
    store = ScenarioStore(str(path))
    scenario = Scenario(name="complete proof", domain=ScenarioDomain.CHAOS_MESH, fault_type="pod_kill")
    await store.put(scenario)
    scenario.touch_status(ScenarioStatus.COMPLETED)
    await store.put(scenario)
    store.close()

    reopened = ScenarioStore(str(path))
    assert (await reopened.get(scenario.id)).status == ScenarioStatus.COMPLETED
    await reopened.remove(scenario.id)
    reopened.close()
    final = ScenarioStore(str(path))
    assert await final.get(scenario.id) is None
    final.close()


@pytest.mark.asyncio
async def test_corrupt_scenario_is_skipped_from_history(tmp_path):
    path = tmp_path / "chaos.db"
    store = ScenarioStore(str(path))
    store._connection.execute(
        "INSERT INTO scenarios (id,status,created_at,document) VALUES (?,?,?,?)",
        ("broken", "failed", datetime.now(timezone.utc).isoformat(), "not-json"),
    )
    store._connection.commit()
    assert await store.list() == []
    store.close()
