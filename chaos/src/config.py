"""
Chaos Injection Engine — configuration
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
    # Service identity (used as `source_agent`/`component` prefix on emitted events)
    SOURCE_AGENT: str = "phoenix"
    SERVICE_NAME: str = "phoenix-chaos"

    # Loki — events are emitted as structured logs, queryable the same way
    # argus's audit log and phoenix-sim's events are:
    # {app="phoenix-chaos"} | json | event_type != ""
    # This is a stub transport: see src/events.py for why, and the M0 note there.
    LOKI_URL: str = os.getenv("LOKI_URL", "http://loki.monitoring.svc.cluster.local:3100")

    # Base URL of the Provisioning Simulator (issue #1) — where "simulator
    # domain" scenarios register/clear fault rules via its /faults API.
    SIMULATOR_URL: str = os.getenv("SIMULATOR_URL", "http://phoenix-sim.phoenix-system.svc.cluster.local")

    # How often the background sweeper re-checks running scenarios against
    # their live backend (a Chaos Mesh experiment's .status, or a simulator
    # fault rule's continued existence) to detect natural completion/expiry
    # and publish a genuine `chaos.scenario.completed` event for it.
    SWEEP_INTERVAL_SECONDS: float = float(os.getenv("SWEEP_INTERVAL_SECONDS", "5.0"))


config = Config()
