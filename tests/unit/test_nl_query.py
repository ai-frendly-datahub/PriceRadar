from __future__ import annotations

import pytest

from priceradar.nl_query import parse_query


@pytest.mark.unit
def test_parse_query_extracts_korean_days_and_limit() -> None:
    parsed = parse_query("최근 7일 닌텐도 특가 5개 보여줘")

    assert parsed.days == 7
    assert parsed.limit == 5
    assert "닌텐도" in parsed.search_text


@pytest.mark.unit
def test_parse_query_extracts_english_days_and_limit() -> None:
    parsed = parse_query("top 10 iphone deals from last 3 days")

    assert parsed.days == 3
    assert parsed.limit == 10
    assert "iphone" in parsed.search_text


@pytest.mark.unit
def test_parse_query_uses_defaults_when_no_filters_provided() -> None:
    parsed = parse_query("apple watch")

    assert parsed.days is None
    assert parsed.limit == 20
    assert parsed.search_text == "apple watch"
