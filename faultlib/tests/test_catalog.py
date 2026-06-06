"""
Tests for the static fault catalog.
Copyright (c) 2026 Kaushikkumaran

These check the catalog's *integrity as reference data* — that it covers
every fault type the other M1 services actually define, that every entry is
populated with the qualitative metadata the issue calls for, and — the part
that matters most for "no fabricated data" — that nothing in it looks like an
invented measurement. They do not (and cannot) check whether a description is
"correct" prose; that's a documentation-review concern, not a testable
invariant. What's testable, and tested, is completeness and the absence of
exactly the kind of content this project must never produce.
"""

import re

import catalog
from models import ScenarioDomain, TaxonomyCategory

# The exact fault-type sets chaos/src/models.py's enums define — duplicated
# here (as chaos's own ChaosMeshFaultType/SimulatorFaultType duplicate
# phoenix-sim's FaultType) so this test fails loudly if either catalog drifts
# out of sync with the engine that actually launches these faults.
CHAOS_MESH_FAULT_TYPES = {"pod_kill", "network_latency", "packet_loss", "io_delay"}
SIMULATOR_FAULT_TYPES = {"latency", "transient_error", "partial_failure", "quota_limit"}

# Patterns that would suggest an entry has drifted from "describes a
# mechanism" into "reports a measurement" — the line this catalog must not cross.
_MEASUREMENT_LIKE = re.compile(r"\b\d+(\.\d+)?\s*(%|percent|ms|seconds?|times|x)\b", re.IGNORECASE)


class TestCoverage:
    def test_every_chaos_mesh_fault_type_is_catalogued(self):
        entries = catalog.for_domain(ScenarioDomain.CHAOS_MESH)
        assert {e.fault_type for e in entries} == CHAOS_MESH_FAULT_TYPES

    def test_every_simulator_fault_type_is_catalogued(self):
        entries = catalog.for_domain(ScenarioDomain.SIMULATOR)
        assert {e.fault_type for e in entries} == SIMULATOR_FAULT_TYPES

    def test_no_duplicate_entries(self):
        keys = [(e.domain, e.fault_type) for e in catalog.all_entries()]
        assert len(keys) == len(set(keys))


class TestEntryCompleteness:
    """Every field the issue asks the library to carry must actually be
    populated — an entry with a blank description/symptoms list would be a
    catalog that promises metadata it doesn't deliver."""

    def test_every_entry_has_populated_metadata(self):
        for entry in catalog.all_entries():
            assert entry.mechanism.strip()
            assert entry.description.strip()
            assert entry.blast_radius_shape.strip()
            assert entry.category_rationale.strip()
            assert len(entry.typical_symptoms) >= 2
            assert all(s.strip() for s in entry.typical_symptoms)

    def test_every_entry_has_a_valid_taxonomy_category(self):
        for entry in catalog.all_entries():
            assert entry.taxonomy_category in TaxonomyCategory


class TestNoFabricatedMeasurements:
    """The catalog describes mechanism, not measurement — see catalog.py's
    module docstring for why a number here would be exactly the kind of
    invented statistic this project must never produce. This guards the
    boundary mechanically: nothing in the prose fields should look like a
    rate, duration, or percentage, because nothing has been *observed* yet
    to make such a number anything but fabricated."""

    def test_no_field_reads_like_a_measured_statistic(self):
        offenders = []
        for entry in catalog.all_entries():
            haystacks = [entry.description, entry.blast_radius_shape, entry.category_rationale, *entry.typical_symptoms]
            for text in haystacks:
                if _MEASUREMENT_LIKE.search(text):
                    offenders.append((entry.domain.value, entry.fault_type, text))
        assert not offenders, f"catalog entries contain measurement-shaped text: {offenders}"


class TestLookup:
    def test_lookup_returns_the_matching_entry(self):
        entry = catalog.lookup(ScenarioDomain.CHAOS_MESH, "pod_kill")
        assert entry is not None
        assert entry.fault_type == "pod_kill"
        assert entry.domain == ScenarioDomain.CHAOS_MESH

    def test_lookup_is_domain_scoped(self):
        # "latency" only exists in the simulator domain — chaos_mesh has no such fault type
        assert catalog.lookup(ScenarioDomain.CHAOS_MESH, "latency") is None
        assert catalog.lookup(ScenarioDomain.SIMULATOR, "latency") is not None

    def test_lookup_returns_none_for_unknown_fault_type(self):
        assert catalog.lookup(ScenarioDomain.CHAOS_MESH, "totally-made-up") is None
