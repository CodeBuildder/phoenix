"""
Tests for chaos_mesh.py's manifest construction and param validation —
pure functions, checked against the *real* chaos-mesh.org/v1alpha1 CRD
field names and enum values (verified directly against the CRDs installed
in the live cluster; see the module docstring), independent of any cluster.
Copyright (c) 2026 Kaushikkumaran
"""

import pytest
from pydantic import ValidationError

import chaos_mesh
from models import ChaosMeshFaultType, K8sTarget


def _target(**overrides):
    base = {"namespace": "phoenix-system", "label_selector": {"app": "phoenix-sim"}}
    base.update(overrides)
    return K8sTarget.model_validate(base)


class TestPodKillManifest:
    def test_builds_pod_chaos_kind(self):
        manifest = chaos_mesh.build_manifest(
            "scn-aaaa111111", ChaosMeshFaultType.POD_KILL, _target(), 30.0,
            chaos_mesh.PodKillParams(),
        )
        assert manifest["apiVersion"] == "chaos-mesh.org/v1alpha1"
        assert manifest["kind"] == "PodChaos"
        assert manifest["spec"]["action"] == "pod-kill"
        assert manifest["spec"]["selector"] == {"namespaces": ["phoenix-system"], "labelSelectors": {"app": "phoenix-sim"}}
        assert manifest["spec"]["mode"] == "one"
        assert manifest["spec"]["duration"] == "30s"

    def test_grace_period_only_set_when_nonzero(self):
        no_grace = chaos_mesh.build_manifest("scn-bbbb", ChaosMeshFaultType.POD_KILL, _target(), None, chaos_mesh.PodKillParams())
        assert "gracePeriod" not in no_grace["spec"]
        assert "duration" not in no_grace["spec"]

        with_grace = chaos_mesh.build_manifest(
            "scn-cccc", ChaosMeshFaultType.POD_KILL, _target(), None, chaos_mesh.PodKillParams(grace_period_seconds=15),
        )
        assert with_grace["spec"]["gracePeriod"] == 15

    def test_metadata_carries_scenario_id_label(self):
        manifest = chaos_mesh.build_manifest("scn-dddd", ChaosMeshFaultType.POD_KILL, _target(), None, chaos_mesh.PodKillParams())
        assert manifest["metadata"]["name"] == "phoenix-chaos-scn-dddd"
        assert manifest["metadata"]["labels"]["phoenix.io/scenario-id"] == "scn-dddd"
        assert manifest["metadata"]["namespace"] == "phoenix-system"


class TestNetworkChaosManifests:
    def test_latency_uses_delay_action_and_subspec(self):
        params = chaos_mesh.NetworkLatencyParams(latency="200ms", jitter="50ms", correlation="25")
        manifest = chaos_mesh.build_manifest("scn-eeee", ChaosMeshFaultType.NETWORK_LATENCY, _target(), 60.0, params)
        assert manifest["kind"] == "NetworkChaos"
        assert manifest["spec"]["action"] == "delay"
        assert manifest["spec"]["delay"] == {"latency": "200ms", "jitter": "50ms", "correlation": "25"}
        assert "loss" not in manifest["spec"]

    def test_packet_loss_uses_loss_action_and_subspec(self):
        params = chaos_mesh.PacketLossParams(loss="40", correlation="10")
        manifest = chaos_mesh.build_manifest("scn-ffff", ChaosMeshFaultType.PACKET_LOSS, _target(), 60.0, params)
        assert manifest["kind"] == "NetworkChaos"
        assert manifest["spec"]["action"] == "loss"
        assert manifest["spec"]["loss"] == {"loss": "40", "correlation": "10"}
        assert "delay" not in manifest["spec"]


class TestIOChaosManifest:
    def test_builds_latency_action_with_path_and_volume(self):
        params = chaos_mesh.IODelayParams(delay="250ms", percent=50, path="/data/**/*", volume_path="/data")
        manifest = chaos_mesh.build_manifest("scn-gggg", ChaosMeshFaultType.IO_DELAY, _target(), 90.0, params)
        assert manifest["kind"] == "IOChaos"
        spec = manifest["spec"]
        assert spec["action"] == "latency"
        assert spec["delay"] == "250ms"
        assert spec["percent"] == 50
        assert spec["path"] == "/data/**/*"
        assert spec["volumePath"] == "/data"
        assert spec["duration"] == "90s"


class TestModeHandling:
    def test_one_and_all_need_no_value(self):
        manifest = chaos_mesh.build_manifest("scn-hhhh", ChaosMeshFaultType.POD_KILL, _target(mode="all"), None, chaos_mesh.PodKillParams())
        assert manifest["spec"]["mode"] == "all"
        assert "value" not in manifest["spec"]

    def test_fixed_modes_reject_a_missing_value_at_construction(self):
        # K8sTarget itself enforces this (see models.py) — by the time a
        # target reaches build_manifest, it's already guaranteed valid.
        for mode in ("fixed", "fixed-percent", "random-max-percent"):
            with pytest.raises(ValidationError, match="target.value is required"):
                _target(mode=mode)

    def test_fixed_mode_with_value_is_carried_through(self):
        manifest = chaos_mesh.build_manifest("scn-jjjj", ChaosMeshFaultType.POD_KILL, _target(mode="fixed-percent", value="50"), None, chaos_mesh.PodKillParams())
        assert manifest["spec"]["mode"] == "fixed-percent"
        assert manifest["spec"]["value"] == "50"


class TestParamValidation:
    def test_unknown_fields_are_ignored_not_fabricated_into_the_model(self):
        # pydantic v2's default `extra="ignore"` — a stray key in the request
        # is dropped, never silently turned into a phantom attribute.
        params = chaos_mesh.parse_params(ChaosMeshFaultType.IO_DELAY, {"delay": "1s", "made_up_field": True})
        assert params.delay == "1s"
        assert not hasattr(params, "made_up_field")

    def test_percent_out_of_range_is_rejected(self):
        with pytest.raises(ValidationError):
            chaos_mesh.parse_params(ChaosMeshFaultType.IO_DELAY, {"percent": 150})

    def test_loss_alias_accepts_the_crds_field_name(self):
        params = chaos_mesh.parse_params(ChaosMeshFaultType.PACKET_LOSS, {"loss": "33"})
        assert params.loss_percent == "33"

    def test_defaults_are_mild(self):
        # A scenario launched with no params should perturb, not annihilate.
        latency = chaos_mesh.parse_params(ChaosMeshFaultType.NETWORK_LATENCY, {})
        assert latency.latency == "100ms"
        kill = chaos_mesh.parse_params(ChaosMeshFaultType.POD_KILL, {})
        assert kill.grace_period_seconds == 0


class TestStatusSummary:
    def test_none_for_empty_status(self):
        assert chaos_mesh.summarize_status(None) is None
        assert chaos_mesh.summarize_status({}) is None

    def test_surfaces_experiment_and_conditions(self):
        raw = {
            "experiment": {"phase": "Running"},
            "conditions": [{"type": "Selected", "status": "True"}],
            "instances": {"pod-a": {}},  # internal bookkeeping we don't surface
        }
        summary = chaos_mesh.summarize_status(raw)
        assert summary == {
            "experiment": {"phase": "Running"},
            "conditions": [{"type": "Selected", "status": "True"}],
        }
        assert "instances" not in summary
