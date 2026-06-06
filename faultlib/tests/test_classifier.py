"""
Tests for the taxonomy classifier.
Copyright (c) 2026 Kaushikkumaran

The classifier is a deterministic lookup, so these tests check exactly that:
every catalogued (domain, fault_type) maps to *some* valid category and to
the *same* category every time, every result traces back to a catalog entry's
own rationale verbatim (nothing is synthesized at classification time), and —
critically — an uncatalogued fault type produces no label at all rather than
a guessed one.
"""

import catalog
import classifier
from models import ScenarioDomain, TaxonomyCategory


class TestKnownFaultTypes:
    def test_every_catalogued_fault_type_classifies(self):
        for entry in catalog.all_entries():
            result = classifier.classify(entry.domain, entry.fault_type)
            assert result is not None
            assert result.taxonomy_category in TaxonomyCategory

    def test_classification_matches_the_catalog_entry_exactly(self):
        """The classifier must not compute its own opinion — it returns
        precisely what the catalog already says about this fault type,
        rationale included, so the two can never silently disagree."""
        for entry in catalog.all_entries():
            result = classifier.classify(entry.domain, entry.fault_type)
            assert result.taxonomy_category == entry.taxonomy_category
            assert result.rationale == entry.category_rationale
            assert result.domain == entry.domain
            assert result.fault_type == entry.fault_type

    def test_classification_is_deterministic(self):
        """The same signature classified twice yields identical results —
        no randomness, no time-of-day dependence, nothing drawn from history."""
        first = classifier.classify(ScenarioDomain.CHAOS_MESH, "network_latency")
        second = classifier.classify(ScenarioDomain.CHAOS_MESH, "network_latency")
        assert first == second


class TestUnknownFaultTypes:
    def test_uncatalogued_fault_type_yields_no_classification(self):
        """No entry, no label — never a best-effort guess. This is the
        guarantee that keeps the classifier from ever inventing a category
        for something it has no real basis to categorize."""
        assert classifier.classify(ScenarioDomain.CHAOS_MESH, "totally-made-up") is None

    def test_fault_type_from_the_wrong_domain_yields_no_classification(self):
        # "latency" is a real fault type — just not one chaos_mesh can run
        assert classifier.classify(ScenarioDomain.CHAOS_MESH, "latency") is None
        assert classifier.classify(ScenarioDomain.SIMULATOR, "latency") is not None


class TestSpecificMappings:
    """Spot-checks the mappings whose rationale is given explicitly in the
    catalog (catalog.py's `category_rationale` fields) — pinning the most
    consequential classifications down by name so a careless edit to the
    catalog's category assignments fails a test, not just a doc review."""

    def test_quota_limit_maps_to_quota_limit(self):
        result = classifier.classify(ScenarioDomain.SIMULATOR, "quota_limit")
        assert result.taxonomy_category == TaxonomyCategory.QUOTA_LIMIT

    def test_network_faults_map_to_network_partition(self):
        for fault_type in ("network_latency", "packet_loss"):
            result = classifier.classify(ScenarioDomain.CHAOS_MESH, fault_type)
            assert result.taxonomy_category == TaxonomyCategory.NETWORK_PARTITION

    def test_pod_kill_maps_to_cascading(self):
        result = classifier.classify(ScenarioDomain.CHAOS_MESH, "pod_kill")
        assert result.taxonomy_category == TaxonomyCategory.CASCADING

    def test_io_delay_maps_to_resource_exhaustion(self):
        result = classifier.classify(ScenarioDomain.CHAOS_MESH, "io_delay")
        assert result.taxonomy_category == TaxonomyCategory.RESOURCE_EXHAUSTION
