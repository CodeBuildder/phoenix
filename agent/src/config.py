"""
Phoenix Agent — configuration
Copyright (c) 2026 Kaushikkumaran
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-6"

    # In-cluster service URLs (k8s DNS)
    CHAOS_URL: str = "http://phoenix-chaos.phoenix-system.svc.cluster.local"
    GRAPH_URL: str = "http://phoenix-graph.phoenix-system.svc.cluster.local"
    FAULTLIB_URL: str = "http://phoenix-faultlib.phoenix-system.svc.cluster.local"

    # Agent behaviour
    POLL_INTERVAL_SECONDS: float = 10.0
    APPROVE_TIMEOUT_SECONDS: float = 300.0   # 5 min — then auto-approve low-risk, abort high-risk
    NAMESPACE: str = "phoenix-system"

    # Memory store
    DB_PATH: str = "/data/memory.db"

    # Event bus (stub: structured log; swap for Redis when sentinel-platform M0 lands)
    SOURCE_AGENT: str = "phoenix"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


config = Config()
