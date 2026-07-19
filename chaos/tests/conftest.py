"""
Shared fixtures for the Chaos Injection Engine test suite.
Copyright (c) 2026 Kaushikkumaran
"""

import os
import sys

os.environ.setdefault("CHAOS_DB_PATH", ":memory:")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from engine import ScenarioEngine
from store import ScenarioStore

from .fakes import FakeChaosMeshClient, FakeSimulatorClient


@pytest.fixture
def fake_chaos_mesh() -> FakeChaosMeshClient:
    return FakeChaosMeshClient()


@pytest.fixture
def fake_simulator() -> FakeSimulatorClient:
    return FakeSimulatorClient()


@pytest.fixture
def engine(fake_chaos_mesh, fake_simulator) -> ScenarioEngine:
    """A fresh engine over an empty store and fresh fake backends for every
    test — no shared state, no live cluster or simulator required."""
    return ScenarioEngine(
        store=ScenarioStore(),
        chaos_mesh=fake_chaos_mesh,
        simulator=fake_simulator,
        sweep_interval_seconds=0.05,
    )
