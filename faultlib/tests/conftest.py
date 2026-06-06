"""
Shared fixtures for the Fault Library & Taxonomy Classifier test suite.
Copyright (c) 2026 Kaushikkumaran
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from .fakes import FakeChaosClient


@pytest.fixture
def fake_chaos() -> FakeChaosClient:
    return FakeChaosClient()
