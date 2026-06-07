"""
Blast-Radius Graph Builder — env-var dependency extractor.
Copyright (c) 2026 Kaushikkumaran

Scans pod environment variables for values that look like k8s service DNS
names and extracts the (source_ns/source_svc, dest_ns/dest_svc) pair.

Pattern matched: http[s]://<name>.<namespace>.svc[.cluster.local][:<port>][/path]
                 <name>.<namespace>.svc[.cluster.local]

Only DNS-name values are considered — not IP addresses, because those require
a ClusterIP reverse-lookup that adds complexity and the DNS form already
expresses the same dependency more clearly.

Every edge this function produces is directly traceable to a specific env var
in a specific pod — nothing is inferred or guessed.
"""

from __future__ import annotations

import re

_K8S_DNS_RE = re.compile(
    r"https?://(?P<name>[a-z0-9-]+)\.(?P<namespace>[a-z0-9-]+)\.svc(?:\.cluster\.local)?(?::\d+)?(?:/.*)?$",
    re.IGNORECASE,
)

_K8S_DNS_BARE_RE = re.compile(
    r"^(?P<name>[a-z0-9-]+)\.(?P<namespace>[a-z0-9-]+)\.svc(?:\.cluster\.local)?$",
    re.IGNORECASE,
)


def parse_service_refs(env: dict[str, str]) -> list[dict[str, str]]:
    """
    Given a pod's environment dict, return a list of service references found.

    Each returned dict has:
        name       — destination service name
        namespace  — destination service namespace
        env_var    — the env var key that carried this reference

    Unknown or malformed values are silently skipped.  An env dict with no
    service references returns an empty list — never a fabricated reference.
    """
    refs: list[dict[str, str]] = []
    for key, value in env.items():
        if not value:
            continue
        m = _K8S_DNS_RE.search(value) or _K8S_DNS_BARE_RE.match(value)
        if m:
            refs.append(
                {
                    "name": m.group("name"),
                    "namespace": m.group("namespace"),
                    "env_var": key,
                }
            )
    return refs
