"""
Tests for component derivation and ranking aggregation.
Copyright (c) 2026 Kaushikkumaran

`build_rankings` is a pure function over whatever scenario records it's
handed — these tests feed it realistically-shaped records (via
tests/fakes.py's `scenario()`) and check that every count in the output
traces back to something genuinely present in the input. The single most
important case here is the empty one: zero real scenarios must yield zero
rankings, not placeholder/sample data — the surest possible guard against
this module ever quietly fabricating something to show.
"""

from aggregator import build_rankings, derive_component
from .fakes import scenario
from models import ScenarioDomain, TaxonomyCategory


class TestDeriveComponent:
    def test_chaos_mesh_component_combines_namespace_and_labels(self):
        target = {"namespace": "phoenix-system", "label_selector": {"app": "phoenix-sim"}}
        assert derive_component(ScenarioDomain.CHAOS_MESH, target) == "phoenix-system/app=phoenix-sim"

    def test_chaos_mesh_component_sorts_multiple_labels_deterministically(self):
        target = {"namespace": "ns", "label_selector": {"tier": "backend", "app": "x"}}
        assert derive_component(ScenarioDomain.CHAOS_MESH, target) == "ns/app=x,tier=backend"

    def test_chaos_mesh_component_falls_back_to_namespace_alone(self):
        target = {"namespace": "phoenix-system", "label_selector": {}}
        assert derive_component(ScenarioDomain.CHAOS_MESH, target) == "phoenix-system"

    def test_chaos_mesh_component_never_invents_a_namespace(self):
        assert derive_component(ScenarioDomain.CHAOS_MESH, {}) == "(no namespace)"

    def test_simulator_component_combines_resource_type_and_operation(self):
        target = {"resource_type": "volume", "operation": "create"}
        assert derive_component(ScenarioDomain.SIMULATOR, target) == "volume/create"

    def test_simulator_component_handles_partial_targets(self):
        assert derive_component(ScenarioDomain.SIMULATOR, {"resource_type": "instance"}) == "instance/*"
        assert derive_component(ScenarioDomain.SIMULATOR, {"operation": "attach"}) == "*/attach"
        assert derive_component(ScenarioDomain.SIMULATOR, {}) == "(unscoped simulator rule)"


class TestBuildRankingsEmptyState:
    def test_no_scenarios_yields_no_rankings(self):
        """The case that matters most: nothing observed -> nothing reported.
        An empty fleet history producing a non-empty ranking would mean this
        module is showing something it didn't actually see."""
        result = build_rankings([])
        assert result.rankings == []
        assert result.scenarios_considered == 0
        assert result.scenarios_excluded == 0


class TestBuildRankingsExclusions:
    def test_scenarios_that_never_started_are_excluded_not_counted(self):
        records = [scenario(started=False), scenario(started=False)]
        result = build_rankings(records)
        assert result.rankings == []
        assert result.scenarios_considered == 0
        assert result.scenarios_excluded == 2

    def test_unclassifiable_fault_types_are_excluded_not_guessed(self):
        records = [scenario(domain="chaos_mesh", fault_type="some-future-fault-type")]
        result = build_rankings(records)
        assert result.rankings == []
        assert result.scenarios_considered == 0
        assert result.scenarios_excluded == 1

    def test_unrecognized_domains_are_excluded(self):
        records = [{**scenario(), "domain": "not-a-real-domain"}]
        result = build_rankings(records)
        assert result.scenarios_excluded == 1
        assert result.scenarios_considered == 0


class TestBuildRankingsTallying:
    def test_one_real_scenario_produces_exactly_one_tally(self):
        records = [scenario(domain="chaos_mesh", fault_type="pod_kill")]
        result = build_rankings(records)

        assert result.scenarios_considered == 1
        assert result.scenarios_excluded == 0
        assert len(result.rankings) == 1

        ranking = result.rankings[0]
        assert ranking.component == "phoenix-system/app=phoenix-sim"
        assert ranking.domain == ScenarioDomain.CHAOS_MESH
        assert ranking.total == 1
        assert ranking.tally.cascading == 1  # pod_kill -> cascading, per the catalog
        assert ranking.tally.transient == 0

    def test_same_component_accumulates_across_categories(self):
        target = {"namespace": "phoenix-system", "label_selector": {"app": "phoenix-sim"}}
        records = [
            scenario(domain="chaos_mesh", fault_type="pod_kill", target=target),
            scenario(domain="chaos_mesh", fault_type="network_latency", target=target),
            scenario(domain="chaos_mesh", fault_type="packet_loss", target=target),
        ]
        result = build_rankings(records)

        assert len(result.rankings) == 1
        ranking = result.rankings[0]
        assert ranking.total == 3
        assert ranking.tally.cascading == 1
        assert ranking.tally.network_partition == 2

    def test_distinct_components_produce_distinct_rankings(self):
        records = [
            scenario(domain="chaos_mesh", fault_type="pod_kill",
                     target={"namespace": "phoenix-system", "label_selector": {"app": "phoenix-sim"}}),
            scenario(domain="simulator", fault_type="quota_limit",
                     target={"resource_type": "volume", "operation": "create"}),
        ]
        result = build_rankings(records)

        assert result.scenarios_considered == 2
        components = {r.component for r in result.rankings}
        assert components == {"phoenix-system/app=phoenix-sim", "volume/create"}

    def test_rankings_are_sorted_by_total_descending(self):
        busy_target = {"namespace": "phoenix-system", "label_selector": {"app": "busy"}}
        quiet_target = {"namespace": "phoenix-system", "label_selector": {"app": "quiet"}}
        records = [
            scenario(domain="chaos_mesh", fault_type="pod_kill", target=quiet_target),
            scenario(domain="chaos_mesh", fault_type="pod_kill", target=busy_target),
            scenario(domain="chaos_mesh", fault_type="network_latency", target=busy_target),
        ]
        result = build_rankings(records)

        assert [r.component for r in result.rankings] == [
            "phoenix-system/app=busy",
            "phoenix-system/app=quiet",
        ]
        assert result.rankings[0].total == 2
        assert result.rankings[1].total == 1

    def test_every_tallied_category_is_one_of_the_five_named_in_the_issue(self):
        records = [scenario(domain=d, fault_type=ft)
                   for d, ft in (("chaos_mesh", "pod_kill"), ("chaos_mesh", "network_latency"),
                                 ("chaos_mesh", "packet_loss"), ("chaos_mesh", "io_delay"),
                                 ("simulator", "latency"), ("simulator", "transient_error"),
                                 ("simulator", "partial_failure"), ("simulator", "quota_limit"))]
        result = build_rankings(records)

        seen = set()
        for ranking in result.rankings:
            for category in TaxonomyCategory:
                if getattr(ranking.tally, category.value.replace("-", "_")) > 0:
                    seen.add(category)
        assert seen == set(TaxonomyCategory)
