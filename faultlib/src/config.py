"""
Fault Library & Taxonomy Classifier — configuration
Copyright (c) 2026 Kaushikkumaran

All configuration loaded from environment variables.
Never hardcode secrets or cluster-specific values.
"""

import os
from pathlib import Path


def _load_local_env() -> None:
    """
    Best-effort .env loader for local development.
    Kubernetes deployments still use pod environment variables / secrets.
    Existing environment variables always win.
    """
    root_env = Path(__file__).resolve().parents[2] / ".env"
    if not root_env.exists():
        return

    for raw_line in root_env.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env()


class Config:
    # Service identity
    SOURCE_AGENT: str = "phoenix"
    SERVICE_NAME: str = "phoenix-faultlib"

    # Base URL of the Chaos Injection Engine (issue #2) — the *only* place
    # this service looks for failure history. Every ranking this service
    # produces is a live tally over scenarios `/chaos` actually ran; nothing
    # is cached, mirrored, or pre-computed here.
    CHAOS_URL: str = os.getenv("CHAOS_URL", "http://phoenix-chaos.phoenix-system.svc.cluster.local")


config = Config()
