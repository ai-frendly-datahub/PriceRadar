"""Pytest configuration for PriceRadar tests."""

from __future__ import annotations

import pytest
import structlog


@pytest.fixture(autouse=True)
def reset_structlog() -> object:
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()
