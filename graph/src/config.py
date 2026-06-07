"""
Blast-Radius Graph Builder — runtime configuration.
Copyright (c) 2026 Kaushikkumaran
"""

import os


def _load_local_env() -> None:
    """Load .env from the src/ directory when running locally (dev/test)."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


_load_local_env()


class Config:
    SOURCE_AGENT: str = "phoenix"
    SERVICE_NAME: str = "phoenix-graph"

    # Hubble relay gRPC address — inside the cluster this is the ClusterIP
    # service that maps port 80 → container port 4245 (insecure gRPC).
    HUBBLE_ADDRESS: str = os.getenv(
        "HUBBLE_ADDRESS", "hubble-relay.kube-system.svc.cluster.local:80"
    )

    # Maximum number of recent flows to pull from Hubble per topology request.
    # The relay merges flows from all cilium-agent ring buffers; too high a
    # value increases sort time and risks hitting the gRPC deadline.
    HUBBLE_MAX_FLOWS: int = int(os.getenv("HUBBLE_MAX_FLOWS", "500"))

    # gRPC call timeout in seconds for the Hubble GetFlows streaming RPC.
    HUBBLE_TIMEOUT_SECONDS: float = float(os.getenv("HUBBLE_TIMEOUT_SECONDS", "15.0"))


config = Config()
