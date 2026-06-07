"""
Tests for the env-var service-reference extractor.
Copyright (c) 2026 Kaushikkumaran

These verify that the parser recognises the k8s DNS URL patterns used in the
real phoenix services and returns nothing for values that aren't service refs.
Every test uses a concrete env dict — no mocking of the parser itself.
"""

from env_parser import parse_service_refs


class TestRecognisedPatterns:
    def test_full_dns_url_with_http(self):
        refs = parse_service_refs(
            {"CHAOS_URL": "http://phoenix-chaos.phoenix-system.svc.cluster.local"}
        )
        assert len(refs) == 1
        assert refs[0]["name"] == "phoenix-chaos"
        assert refs[0]["namespace"] == "phoenix-system"
        assert refs[0]["env_var"] == "CHAOS_URL"

    def test_url_with_port(self):
        refs = parse_service_refs(
            {"LOKI_URL": "http://loki.monitoring.svc.cluster.local:3100"}
        )
        assert len(refs) == 1
        assert refs[0]["name"] == "loki"
        assert refs[0]["namespace"] == "monitoring"

    def test_url_with_path(self):
        refs = parse_service_refs(
            {"API": "http://my-svc.my-ns.svc.cluster.local/api/v1"}
        )
        assert len(refs) == 1
        assert refs[0]["name"] == "my-svc"
        assert refs[0]["namespace"] == "my-ns"

    def test_short_svc_suffix(self):
        refs = parse_service_refs(
            {"X": "http://foo.bar.svc"}
        )
        assert len(refs) == 1
        assert refs[0]["name"] == "foo"
        assert refs[0]["namespace"] == "bar"

    def test_https_url(self):
        refs = parse_service_refs(
            {"TLS": "https://secure-svc.kube-system.svc.cluster.local"}
        )
        assert len(refs) == 1
        assert refs[0]["name"] == "secure-svc"
        assert refs[0]["namespace"] == "kube-system"

    def test_multiple_refs_in_one_pod(self):
        refs = parse_service_refs(
            {
                "CHAOS_URL": "http://phoenix-chaos.phoenix-system.svc.cluster.local",
                "SIMULATOR_URL": "http://phoenix-sim.phoenix-system.svc.cluster.local",
                "LOG_LEVEL": "info",
            }
        )
        names = {r["name"] for r in refs}
        assert names == {"phoenix-chaos", "phoenix-sim"}


class TestIgnoredValues:
    def test_plain_ip_address_is_ignored(self):
        refs = parse_service_refs({"HOST": "10.43.172.2"})
        assert refs == []

    def test_external_url_is_ignored(self):
        refs = parse_service_refs({"REMOTE": "https://api.example.com/v1"})
        assert refs == []

    def test_empty_value_is_ignored(self):
        refs = parse_service_refs({"CHAOS_URL": ""})
        assert refs == []

    def test_empty_env_yields_no_refs(self):
        assert parse_service_refs({}) == []

    def test_non_url_string_is_ignored(self):
        refs = parse_service_refs({"DEBUG": "true", "PORT": "8000"})
        assert refs == []
