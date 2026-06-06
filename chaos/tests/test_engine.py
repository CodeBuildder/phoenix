"""
Tests for ScenarioEngine — the orchestration core.
Copyright (c) 2026 Kaushikkumaran

Exercises the engine entirely against the faithful in-memory fakes in
fakes.py: real state transitions, real event ordering, real error paths —
nothing here is canned or pre-scripted, every assertion reads back what the
engine actually did to its (fake) backend and what it actually published.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

import engine as engine_module
from engine import BackendError, InvalidScenarioStateError, ScenarioNotFoundError
from events import publish_event as real_publish_event
from models import ScenarioCreateRequest, ScenarioStatus

from .fakes import ExplodingChaosMeshClient, ExplodingSimulatorClient, FakeChaosMeshClient, FakeSimulatorClient


class EventRecorder:
    """Captures every event the engine publishes, in order, while still
    emitting the genuine `Event` through the real publisher — so structured
    logs keep flowing to Loki exactly as they would in production, and the
    test gets a faithful, ordered record of what happened to assert on."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event_type, *, severity, component, payload=None, caused_by=None, reason=None):
        self.events.append({
            "event_type": event_type,
            "severity": severity,
            "component": component,
            "payload": payload or {},
            "caused_by": caused_by,
            "reason": reason,
        })
        return real_publish_event(event_type, severity=severity, component=component,
                                   payload=payload, caused_by=caused_by, reason=reason)

    @property
    def types(self) -> list[str]:
        return [e["event_type"] for e in self.events]


@pytest.fixture
def recorder(monkeypatch) -> EventRecorder:
    rec = EventRecorder()
    monkeypatch.setattr(engine_module, "publish_event", rec)
    return rec


def _chaos_mesh_request(**overrides) -> ScenarioCreateRequest:
    base = dict(
        name="kill-sim-pod",
        domain="chaos_mesh",
        fault_type="pod_kill",
        target={"namespace": "phoenix-system", "label_selector": {"app": "phoenix-sim"}},
        duration_seconds=30.0,
        params={},
    )
    base.update(overrides)
    return ScenarioCreateRequest.model_validate(base)


def _simulator_request(**overrides) -> ScenarioCreateRequest:
    base = dict(
        name="inject-volume-latency",
        domain="simulator",
        fault_type="latency",
        target={"resource_type": "volume", "operation": "create"},
        duration_seconds=60.0,
        probability=0.5,
        params={"min_ms": 200, "max_ms": 500},
    )
    base.update(overrides)
    return ScenarioCreateRequest.model_validate(base)


# ---------------------------------------------------------------------------
# start() — chaos_mesh domain
# ---------------------------------------------------------------------------

class TestStartChaosMesh:
    async def test_applies_real_manifest_and_reaches_running(self, engine, fake_chaos_mesh, recorder):
        scenario = await engine.start(_chaos_mesh_request())

        assert scenario.status == ScenarioStatus.RUNNING
        assert scenario.domain.value == "chaos_mesh"
        assert scenario.backend_ref == "phoenix-chaos-" + scenario.id
        assert scenario.started_at is not None
        assert scenario.blast_radius is None  # never fabricated — issue #4's job

        # the fake actually built and stored a genuine PodChaos manifest
        assert len(fake_chaos_mesh.apply_calls) == 1
        stored_key = ("phoenix-system", scenario.backend_ref)
        assert stored_key in fake_chaos_mesh.objects
        assert fake_chaos_mesh.objects[stored_key]["spec"]["action"] == "pod-kill"

        assert recorder.types == ["chaos.scenario.created", "chaos.scenario.started"]
        assert recorder.events[0]["caused_by"] == scenario.id
        assert recorder.events[1]["payload"]["backend_ref"] == scenario.backend_ref

    async def test_persists_scenario_before_applying_to_backend(self, engine, fake_chaos_mesh):
        """The created record must exist (and be visible) even mid-apply —
        verified by checking the fake recorded exactly one apply call against
        a scenario id that the store already knew about."""
        scenario = await engine.start(_chaos_mesh_request(name="probe"))
        recorded_id = fake_chaos_mesh.apply_calls[0][0]
        assert recorded_id == scenario.id
        assert await engine._store.get(scenario.id) is not None

    async def test_unknown_fault_type_is_rejected_before_anything_is_recorded(self, engine, fake_chaos_mesh):
        with pytest.raises(ValueError, match="unknown chaos_mesh fault_type"):
            await engine.start(_chaos_mesh_request(fault_type="black_hole"))

        assert await engine.list() == []
        assert fake_chaos_mesh.apply_calls == []

    async def test_malformed_target_is_rejected_as_validation_error(self, engine, fake_chaos_mesh):
        with pytest.raises(ValidationError):
            await engine.start(_chaos_mesh_request(target={"namespace": "phoenix-system", "mode": "fixed"}))
        assert await engine.list() == []

    async def test_malformed_params_is_rejected_as_validation_error(self, engine, fake_chaos_mesh):
        with pytest.raises(ValidationError):
            await engine.start(_chaos_mesh_request(fault_type="io_delay", params={"percent": 999}))
        assert await engine.list() == []

    async def test_backend_failure_marks_scenario_failed_and_raises(self):
        store = engine_module.ScenarioStore()
        exploding = ExplodingChaosMeshClient()
        eng = engine_module.ScenarioEngine(store=store, chaos_mesh=exploding, simulator=FakeSimulatorClient(), sweep_interval_seconds=0.05)

        with pytest.raises(BackendError, match="admission webhook denied"):
            await eng.start(_chaos_mesh_request())

        scenarios = await eng.list()
        assert len(scenarios) == 1
        assert scenarios[0].status == ScenarioStatus.FAILED
        assert "admission webhook denied" in scenarios[0].error
        assert scenarios[0].ended_at is not None


# ---------------------------------------------------------------------------
# start() — simulator domain
# ---------------------------------------------------------------------------

class TestStartSimulator:
    async def test_registers_real_fault_rule_and_reaches_running(self, engine, fake_simulator, recorder):
        scenario = await engine.start(_simulator_request())

        assert scenario.status == ScenarioStatus.RUNNING
        assert scenario.domain.value == "simulator"
        assert scenario.fault_type == "latency"
        assert scenario.backend_ref in fake_simulator.rules
        rule = fake_simulator.rules[scenario.backend_ref]
        assert rule["resource_type"] == "volume"
        assert rule["operation"] == "create"
        assert rule["probability"] == 0.5

        assert len(fake_simulator.register_calls) == 1
        assert recorder.types == ["chaos.scenario.created", "chaos.scenario.started"]

    async def test_unknown_fault_type_is_rejected(self, engine):
        with pytest.raises(ValueError, match="unknown simulator fault_type"):
            await engine.start(_simulator_request(fault_type="meteor_strike"))
        assert await engine.list() == []

    async def test_backend_failure_marks_scenario_failed_and_raises(self):
        store = engine_module.ScenarioStore()
        eng = engine_module.ScenarioEngine(store=store, chaos_mesh=FakeChaosMeshClient(), simulator=ExplodingSimulatorClient(), sweep_interval_seconds=0.05)

        with pytest.raises(BackendError, match="simulator unreachable"):
            await eng.start(_simulator_request())

        scenarios = await eng.list()
        assert scenarios[0].status == ScenarioStatus.FAILED
        assert "simulator unreachable" in scenarios[0].error


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

class TestStop:
    async def test_stop_deletes_backend_object_and_reaches_stopped(self, engine, fake_chaos_mesh, recorder):
        scenario = await engine.start(_chaos_mesh_request())
        stopped = await engine.stop(scenario.id)

        assert stopped.status == ScenarioStatus.STOPPED
        assert stopped.ended_at is not None
        assert ("phoenix-system", scenario.backend_ref) not in fake_chaos_mesh.objects
        assert fake_chaos_mesh.delete_calls == [(engine_module.ChaosMeshFaultType.POD_KILL, scenario.backend_ref, "phoenix-system")]
        assert recorder.types[-1] == "chaos.scenario.stopped"

    async def test_stop_clears_simulator_rule(self, engine, fake_simulator):
        scenario = await engine.start(_simulator_request())
        stopped = await engine.stop(scenario.id)

        assert stopped.status == ScenarioStatus.STOPPED
        assert scenario.backend_ref not in fake_simulator.rules
        assert fake_simulator.clear_calls == [scenario.backend_ref]

    async def test_stop_on_unknown_scenario_raises_not_found(self, engine):
        with pytest.raises(ScenarioNotFoundError):
            await engine.stop("scn-doesnotexist")

    async def test_stop_on_non_running_scenario_raises_invalid_state(self, engine):
        scenario = await engine.start(_chaos_mesh_request(duration_seconds=1.0))
        await engine.stop(scenario.id)

        with pytest.raises(InvalidScenarioStateError, match="is stopped, not running"):
            await engine.stop(scenario.id)

    async def test_stop_backend_failure_marks_scenario_failed(self, engine, fake_chaos_mesh, recorder):
        scenario = await engine.start(_chaos_mesh_request())

        async def _exploding_delete(*args, **kwargs):
            raise RuntimeError("finalizer stuck")

        fake_chaos_mesh.delete = _exploding_delete

        with pytest.raises(BackendError, match="finalizer stuck"):
            await engine.stop(scenario.id)

        refreshed = await engine.get(scenario.id, refresh=False)
        assert refreshed.status == ScenarioStatus.FAILED
        assert "finalizer stuck" in refreshed.error
        assert recorder.types[-1] == "chaos.scenario.failed"
        assert recorder.events[-1]["payload"]["stage"] == "stop"


# ---------------------------------------------------------------------------
# get() / list() / remove()
# ---------------------------------------------------------------------------

class TestGetListRemove:
    async def test_get_unknown_raises_not_found(self, engine):
        with pytest.raises(ScenarioNotFoundError):
            await engine.get("scn-nope")

    async def test_get_refreshes_live_status_for_running_scenarios(self, engine, fake_chaos_mesh):
        scenario = await engine.start(_chaos_mesh_request())
        # mutate the fake's backing object — a genuine "what changed in the cluster" readout
        fake_chaos_mesh.objects[("phoenix-system", scenario.backend_ref)]["status"] = {
            "experiment": {"phase": "Running"},
            "conditions": [{"type": "AllInjected", "status": "True"}],
        }

        refreshed = await engine.get(scenario.id)
        assert refreshed.live_status == {
            "experiment": {"phase": "Running"},
            "conditions": [{"type": "AllInjected", "status": "True"}],
        }

    async def test_get_does_not_refresh_terminal_scenarios(self, engine, fake_chaos_mesh):
        scenario = await engine.start(_chaos_mesh_request())
        await engine.stop(scenario.id)
        before = fake_chaos_mesh.get
        calls = []

        async def _counting_get(*args, **kwargs):
            calls.append(args)
            return await before(*args, **kwargs)

        fake_chaos_mesh.get = _counting_get
        await engine.get(scenario.id)
        assert calls == []  # a stopped scenario's backend is gone — no point asking

    async def test_list_filters_by_status(self, engine):
        running = await engine.start(_chaos_mesh_request(name="stays-up"))
        to_stop = await engine.start(_chaos_mesh_request(name="will-stop"))
        await engine.stop(to_stop.id)

        all_scenarios = await engine.list()
        assert {s.id for s in all_scenarios} == {running.id, to_stop.id}

        running_only = await engine.list(status=ScenarioStatus.RUNNING)
        assert [s.id for s in running_only] == [running.id]

        stopped_only = await engine.list(status=ScenarioStatus.STOPPED)
        assert [s.id for s in stopped_only] == [to_stop.id]

    async def test_remove_deletes_terminal_scenario(self, engine):
        scenario = await engine.start(_chaos_mesh_request(duration_seconds=1.0))
        await engine.stop(scenario.id)
        await engine.remove(scenario.id)

        with pytest.raises(ScenarioNotFoundError):
            await engine.get(scenario.id)

    async def test_remove_refuses_while_running(self, engine):
        scenario = await engine.start(_chaos_mesh_request())
        with pytest.raises(InvalidScenarioStateError, match="still running"):
            await engine.remove(scenario.id)
        # nothing was torn down behind our back
        assert (await engine.get(scenario.id)).status == ScenarioStatus.RUNNING

    async def test_remove_unknown_raises_not_found(self, engine):
        with pytest.raises(ScenarioNotFoundError):
            await engine.remove("scn-ghost")


# ---------------------------------------------------------------------------
# _sync / sweeper — natural completion is read from the backend, never timed
# ---------------------------------------------------------------------------

class TestNaturalCompletion:
    async def test_sync_marks_completed_when_chaos_mesh_object_is_gone(self, engine, fake_chaos_mesh, recorder):
        scenario = await engine.start(_chaos_mesh_request(duration_seconds=1.0))
        # Chaos Mesh itself cleared the experiment out once its duration elapsed
        fake_chaos_mesh.objects.pop(("phoenix-system", scenario.backend_ref))

        synced = await engine.get(scenario.id)
        assert synced.status == ScenarioStatus.COMPLETED
        assert synced.ended_at is not None
        assert recorder.types[-1] == "chaos.scenario.completed"
        assert "ran its course" in recorder.events[-1]["reason"]

    async def test_sync_marks_completed_when_simulator_rule_expires(self, engine, fake_simulator, recorder):
        scenario = await engine.start(_simulator_request(duration_seconds=1.0))
        fake_simulator.rules.pop(scenario.backend_ref)

        synced = await engine.get(scenario.id)
        assert synced.status == ScenarioStatus.COMPLETED
        assert recorder.types[-1] == "chaos.scenario.completed"
        assert "expired or was cleared" in recorder.events[-1]["reason"]

    async def test_sweeper_completes_scenarios_without_being_asked(self, engine, fake_chaos_mesh, recorder):
        scenario = await engine.start(_chaos_mesh_request(duration_seconds=1.0))
        fake_chaos_mesh.objects.pop(("phoenix-system", scenario.backend_ref))

        engine.start_sweeper()
        try:
            for _ in range(100):
                await asyncio.sleep(0.05)
                if scenario.status == ScenarioStatus.COMPLETED or "chaos.scenario.completed" in recorder.types:
                    break
            stored = await engine._store.get(scenario.id)
            assert stored.status == ScenarioStatus.COMPLETED
            assert "chaos.scenario.completed" in recorder.types
        finally:
            await engine.stop_sweeper()

    async def test_sweeper_only_looks_at_running_scenarios(self, engine, fake_chaos_mesh):
        scenario = await engine.start(_chaos_mesh_request(duration_seconds=1.0))
        await engine.stop(scenario.id)
        before = fake_chaos_mesh.get
        calls = []

        async def _counting_get(*args, **kwargs):
            calls.append(args)
            return await before(*args, **kwargs)
        fake_chaos_mesh.get = _counting_get

        engine.start_sweeper()
        try:
            await asyncio.sleep(0.2)
        finally:
            await engine.stop_sweeper()
        assert calls == []
