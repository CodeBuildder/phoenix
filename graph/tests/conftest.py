"""Shared pytest fixtures for the graph service tests."""

import sys
import os
import pytest

# Add src/ to the path so tests can import the service modules directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from .fakes import FakeHubbleClient, FakeK8sClient  # noqa: E402


@pytest.fixture
def empty_k8s() -> FakeK8sClient:
    return FakeK8sClient()


@pytest.fixture
def empty_hubble() -> FakeHubbleClient:
    return FakeHubbleClient()
