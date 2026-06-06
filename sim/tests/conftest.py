"""
Shared fixtures for the Provisioning Simulator test suite.
Copyright (c) 2026 Kaushikkumaran
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from config import config
from faults import injector
from store import store


@pytest.fixture(autouse=True)
async def _isolated_fast_simulator():
    """Every test starts from an empty store and fault registry, and runs
    lifecycle transitions fast — real ones take 0.2-3s; tests shouldn't."""
    previous_speed = config.LIFECYCLE_SPEED
    config.LIFECYCLE_SPEED = 0.01
    await store.clear()
    injector.clear_all()
    yield
    await store.clear()
    injector.clear_all()
    config.LIFECYCLE_SPEED = previous_speed
