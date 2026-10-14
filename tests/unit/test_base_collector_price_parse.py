"""Regression guard for BaseCollector._parse_price_value.

Earlier the helper replaced commas with spaces, which silently truncated every
multi-digit Korean price ("14,460원" -> "14"). All Radars sharing this helper
returned mostly-null current_price values for human-readable price strings.
The fix removes commas entirely so the thousands separator no longer splits
the number.
"""

from __future__ import annotations

import pytest

from priceradar.collectors.base import BaseCollector


class _StubCollector(BaseCollector):
    def collect(self):  # type: ignore[override]
        return []


@pytest.fixture()
def collector() -> _StubCollector:
    return _StubCollector(
        "stub", {"name": "stub", "type": "stub", "url": "http://example", "category": "x"}
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("14,460원", 14460),
        ("14,460", 14460),
        ("￦ 14,460 (KRW)", 14460),
        ("1,234,567원", 1234567),
        ("548,000원/무료", 548000),
        ("11,200원 (배송비 0원)", 11200),
        ("$1,299", 1299),
        ("€ 9,999", 9999),
        ("500", 500),
        ("500원", 500),
    ],
)
def test_parses_comma_thousands_separator(
    collector: _StubCollector, value: str, expected: int
) -> None:
    assert collector._parse_price_value(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, "", "  ", "N/A", "n/a", "null", "-", "--", "0", 0, -1, True, False],
)
def test_returns_none_for_empty_or_zero(collector: _StubCollector, value: object) -> None:
    assert collector._parse_price_value(value) is None


def test_int_passthrough_positive(collector: _StubCollector) -> None:
    assert collector._parse_price_value(12345) == 12345


def test_float_passthrough(collector: _StubCollector) -> None:
    assert collector._parse_price_value(12345.7) == 12345


def test_title_year_is_not_a_price(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A model year in a title must not be stored as current_price."""
    monkeypatch.setenv("RADAR_CRAWL_HEALTH_DB_PATH", str(tmp_path / "health.duckdb"))
    from priceradar.collectors.clien_collector import ClienCollector
    from priceradar.collectors.fmkorea_collector import FmkoreaCollector
    from priceradar.collectors.quasarzone_collector import QuasarzoneCollector

    title = "[캉골] 2026 시크릿 세일"
    priced = "[카카오] 하겐다즈 파인트 4개 (28,710원)"
    collectors = [
        ClienCollector("clien", {"url": "https://www.clien.net/service/board/jirum"}),
        FmkoreaCollector("fmkorea", {"url": "https://www.fmkorea.com/hotdeal"}),
        QuasarzoneCollector("quasarzone", {"url": "https://quasarzone.com/bbs/qb_saleinfo"}),
    ]
    for collector in collectors:
        assert collector._extract_price_from_title(title) is None
        assert collector._extract_price_from_title(priced) == 28710
