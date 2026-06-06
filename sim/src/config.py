"""
Provisioning Simulator — configuration
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
    SERVICE_NAME: str = "phoenix-sim"

    # Loki — events are emitted as structured logs, queryable the same way
    # argus's audit log is: {app="phoenix-sim"} | json | event_type != ""
    # This is a stub transport: see src/events.py for why, and the M0 note there.
    LOKI_URL: str = os.getenv("LOKI_URL", "http://loki.monitoring.svc.cluster.local:3100")

    # Lifecycle pacing — multiplies the base simulated delay for every resource
    # transition. Lower for fast local iteration, raise for more "realistic" demos.
    LIFECYCLE_SPEED: float = float(os.getenv("LIFECYCLE_SPEED", "1.0"))

    # Per-resource-type quotas. Exceeding one yields a `quota_limit` fault
    # response even with no fault rule registered — mirrors how real
    # infrastructure ops fail under load, and gives the chaos engine a
    # deterministic target to aim at.
    VOLUME_QUOTA: int = int(os.getenv("VOLUME_QUOTA", "50"))
    SUBNET_QUOTA: int = int(os.getenv("SUBNET_QUOTA", "20"))
    INSTANCE_QUOTA: int = int(os.getenv("INSTANCE_QUOTA", "30"))


config = Config()
