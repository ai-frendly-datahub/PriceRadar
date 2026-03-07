"""
Unit tests for priceradar.validators module.

Tests cover:
- Title normalization
- URL similarity detection
- Price range validation
- Discount rate validation
- URL format validation
- Duplicate product detection
"""

from __future__ import annotations

import pytest

from priceradar.validators import (
    detect_duplicate_articles,
    detect_duplicate_products,
    is_similar_url,
    normalize_title,
    validate_article,
    validate_discount_rate,
    validate_price_range,
    validate_url_format,
)


class TestNormalizeTitle:
    """Tests for normalize_title function."""

    def test_normalize_basic_title(self) -> None:
        result = normalize_title("Samsung Galaxy S24")
        assert result == "samsung galaxy s24"

    def test_normalize_extra_whitespace(self) -> None:
        result = normalize_title("  Samsung  Galaxy  S24  ")
        assert result == "samsung galaxy s24"

    def test_normalize_with_parentheses(self) -> None:
        result = normalize_title("iPhone 15 Pro (256GB)")
        assert result == "iphone 15 pro 256gb"

    def test_normalize_with_brackets(self) -> None:
        result = normalize_title("Product [New Version]")
        assert result == "product new version"

    def test_normalize_special_characters(self) -> None:
        result = normalize_title("Product@#$%Name")
        assert result == "productname"

    def test_normalize_with_hyphens(self) -> None:
        result = normalize_title("Samsung Galaxy S24-Ultra")
        assert result == "samsung galaxy s24-ultra"

    def test_normalize_empty_string(self) -> None:
        result = normalize_title("")
        assert result == ""

    def test_normalize_only_whitespace(self) -> None:
        result = normalize_title("   ")
        assert result == ""

    def test_normalize_complex_title(self) -> None:
        result = normalize_title("  Apple iPhone 15 Pro Max (512GB) [2024]  ")
        assert result == "apple iphone 15 pro max 512gb 2024"

    def test_normalize_korean_characters(self) -> None:
        result = normalize_title("삼성 갤럭시 S24")
        assert result == "삼성 갤럭시 s24"


class TestIsSimilarUrl:
    """Tests for is_similar_url function."""

    def test_identical_urls(self) -> None:
        url = "https://coupang.com/vp/products/123"
        assert is_similar_url(url, url) is True

    def test_same_domain_same_path(self) -> None:
        url1 = "https://coupang.com/vp/products/123"
        url2 = "https://coupang.com/vp/products/123?ref=abc"
        assert is_similar_url(url1, url2) is True

    def test_different_domains(self) -> None:
        url1 = "https://coupang.com/vp/products/123"
        url2 = "https://naver.com/vp/products/123"
        assert is_similar_url(url1, url2) is False

    def test_different_paths(self) -> None:
        url1 = "https://coupang.com/vp/products/123"
        url2 = "https://coupang.com/vp/products/456"
        assert is_similar_url(url1, url2) is True

    def test_similar_paths_high_threshold(self) -> None:
        url1 = "https://coupang.com/vp/products/123"
        url2 = "https://coupang.com/vp/products/124"
        assert is_similar_url(url1, url2, threshold=0.95) is False

    def test_similar_paths_low_threshold(self) -> None:
        url1 = "https://coupang.com/vp/products/123"
        url2 = "https://coupang.com/vp/products/124"
        assert is_similar_url(url1, url2, threshold=0.5) is True

    def test_invalid_url_format(self) -> None:
        url1 = "not-a-url"
        url2 = "https://coupang.com/vp/products/123"
        assert is_similar_url(url1, url2) is False

    def test_empty_urls(self) -> None:
        assert is_similar_url("", "") is True

    def test_url_with_fragments(self) -> None:
        url1 = "https://coupang.com/vp/products/123"
        url2 = "https://coupang.com/vp/products/123#section"
        assert is_similar_url(url1, url2) is True


class TestValidatePriceRange:
    """Tests for validate_price_range function."""

    def test_valid_price_middle_range(self) -> None:
        assert validate_price_range(10000) is True

    def test_valid_price_minimum(self) -> None:
        assert validate_price_range(100) is True

    def test_valid_price_maximum(self) -> None:
        assert validate_price_range(1_000_000_000) is True

    def test_invalid_price_below_minimum(self) -> None:
        assert validate_price_range(50) is False

    def test_invalid_price_above_maximum(self) -> None:
        assert validate_price_range(2_000_000_000) is False

    def test_none_price_is_valid(self) -> None:
        assert validate_price_range(None) is True

    def test_zero_price_is_invalid(self) -> None:
        assert validate_price_range(0) is False

    def test_negative_price_is_invalid(self) -> None:
        assert validate_price_range(-1000) is False

    def test_custom_min_price(self) -> None:
        assert validate_price_range(500, min_price=1000) is False

    def test_custom_max_price(self) -> None:
        assert validate_price_range(500_000_000, max_price=100_000_000) is False


class TestValidateDiscountRate:
    """Tests for validate_discount_rate function."""

    def test_valid_discount_zero(self) -> None:
        assert validate_discount_rate(0.0) is True

    def test_valid_discount_fifty_percent(self) -> None:
        assert validate_discount_rate(0.5) is True

    def test_valid_discount_hundred_percent(self) -> None:
        assert validate_discount_rate(1.0) is True

    def test_invalid_discount_above_one(self) -> None:
        assert validate_discount_rate(1.5) is False

    def test_invalid_discount_negative(self) -> None:
        assert validate_discount_rate(-0.1) is False

    def test_none_discount_is_valid(self) -> None:
        assert validate_discount_rate(None) is True

    def test_valid_discount_small_value(self) -> None:
        assert validate_discount_rate(0.01) is True

    def test_valid_discount_large_value(self) -> None:
        assert validate_discount_rate(0.99) is True


class TestValidateUrlFormat:
    """Tests for validate_url_format function."""

    def test_valid_https_url(self) -> None:
        assert validate_url_format("https://coupang.com/vp/products/123") is True

    def test_valid_http_url(self) -> None:
        assert validate_url_format("http://example.com") is True

    def test_invalid_url_no_scheme(self) -> None:
        assert validate_url_format("coupang.com/vp/products/123") is False

    def test_invalid_url_no_domain(self) -> None:
        assert validate_url_format("https://") is False

    def test_invalid_url_empty_string(self) -> None:
        assert validate_url_format("") is False

    def test_invalid_url_not_a_url(self) -> None:
        assert validate_url_format("not-a-url") is False

    def test_invalid_url_none_type(self) -> None:
        assert validate_url_format(None) is False

    def test_valid_url_with_query_params(self) -> None:
        assert validate_url_format("https://coupang.com/vp/products/123?ref=abc") is True

    def test_valid_url_with_fragment(self) -> None:
        assert validate_url_format("https://coupang.com/vp/products/123#section") is True


class TestDetectDuplicateProducts:
    """Tests for detect_duplicate_products function."""

    def test_identical_products(self) -> None:
        assert (
            detect_duplicate_products(
                "Samsung Galaxy S24",
                "https://coupang.com/vp/products/123",
                "Samsung Galaxy S24",
                "https://coupang.com/vp/products/123",
            )
            is True
        )

    def test_same_title_same_url_with_query_params(self) -> None:
        assert (
            detect_duplicate_products(
                "Samsung Galaxy S24",
                "https://coupang.com/vp/products/123",
                "Samsung Galaxy S24",
                "https://coupang.com/vp/products/123?ref=abc",
            )
            is True
        )

    def test_different_titles_same_url(self) -> None:
        assert (
            detect_duplicate_products(
                "Samsung Galaxy S24",
                "https://coupang.com/vp/products/123",
                "Galaxy S24",
                "https://coupang.com/vp/products/123",
            )
            is False
        )

    def test_same_title_different_urls(self) -> None:
        assert (
            detect_duplicate_products(
                "Samsung Galaxy S24",
                "https://coupang.com/vp/products/123",
                "Samsung Galaxy S24",
                "https://naver.com/vp/products/456",
            )
            is False
        )

    def test_similar_titles_similar_urls(self) -> None:
        assert (
            detect_duplicate_products(
                "  Samsung Galaxy S24  ",
                "https://coupang.com/vp/products/123",
                "Samsung Galaxy S24",
                "https://coupang.com/vp/products/123?ref=abc",
            )
            is True
        )

    def test_titles_with_special_chars(self) -> None:
        assert (
            detect_duplicate_products(
                "iPhone 15 Pro (256GB)",
                "https://coupang.com/vp/products/123",
                "iPhone 15 Pro 256GB",
                "https://coupang.com/vp/products/123",
            )
            is True
        )

    def test_custom_thresholds_strict(self) -> None:
        assert (
            detect_duplicate_products(
                "Samsung Galaxy S24",
                "https://coupang.com/vp/products/123",
                "Samsung Galaxy S24 Ultra",
                "https://coupang.com/vp/products/123",
                title_threshold=0.99,
            )
            is False
        )

    def test_custom_thresholds_lenient(self) -> None:
        assert (
            detect_duplicate_products(
                "Samsung Galaxy S24",
                "https://coupang.com/vp/products/123",
                "Samsung Galaxy S24 Ultra",
                "https://coupang.com/vp/products/123",
                title_threshold=0.7,
            )
            is True
        )

    def test_empty_titles(self) -> None:
        assert (
            detect_duplicate_products(
                "",
                "https://coupang.com/vp/products/123",
                "",
                "https://coupang.com/vp/products/123",
            )
            is True
        )


class TestDetectDuplicateArticlesAlias:
    def test_alias_matches_product_duplicate_logic(self) -> None:
        assert (
            detect_duplicate_articles(
                "Nintendo Switch OLED",
                "https://shop.example.com/p/1",
                "Nintendo Switch OLED",
                "https://shop.example.com/p/1?utm=abc",
            )
            is True
        )


class TestValidateArticle:
    def test_validate_article_with_raw_item_dict(self) -> None:
        article = {
            "title": "닌텐도 스위치 OLED",
            "url": "https://shop.example.com/p/1",
            "category": "game",
            "platform": "coupang",
            "source": "fallcent",
            "current_price": 390000,
            "avg_price": 430000,
            "list_price": 450000,
            "discount_rate": 0.13,
        }
        is_valid, errors = validate_article(article)
        assert is_valid is True
        assert errors == []

    def test_validate_article_invalid_price(self) -> None:
        article = {
            "title": "닌텐도 스위치 OLED",
            "url": "https://shop.example.com/p/1",
            "category": "game",
            "platform": "coupang",
            "source": "fallcent",
            "current_price": 50,
            "discount_rate": 0.13,
        }
        is_valid, errors = validate_article(article)
        assert is_valid is False
        assert any("current_price out of range" in error for error in errors)


@pytest.mark.unit
class TestValidatorsIntegration:
    """Integration tests for validators."""

    def test_full_product_validation_flow(self) -> None:
        title1 = "  Apple iPhone 15 Pro Max  "
        url1 = "https://coupang.com/vp/products/123"
        price1 = 1_500_000
        discount1 = 0.15

        title2 = "Apple iPhone 15 Pro Max"
        url2 = "https://coupang.com/vp/products/123?ref=abc"
        price2 = 1_500_000
        discount2 = 0.15

        assert normalize_title(title1) == normalize_title(title2)
        assert validate_url_format(url1) is True
        assert validate_url_format(url2) is True
        assert validate_price_range(price1) is True
        assert validate_price_range(price2) is True
        assert validate_discount_rate(discount1) is True
        assert validate_discount_rate(discount2) is True
        assert detect_duplicate_products(title1, url1, title2, url2) is True

    def test_invalid_product_validation_flow(self) -> None:
        title = "Product"
        url = "not-a-url"
        price = 50
        discount = 1.5

        assert validate_url_format(url) is False
        assert validate_price_range(price) is False
        assert validate_discount_rate(discount) is False
