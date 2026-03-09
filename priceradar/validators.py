"""
Data validation utilities for PriceRadar.

Provides functions for:
- Title normalization (whitespace, special characters)
- URL similarity detection
- Price range validation
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Optional
from urllib.parse import urlparse


def normalize_title(title: str) -> str:
    """
    Normalize product title by removing extra whitespace and special characters.

    Args:
        title: Raw product title

    Returns:
        Normalized title (lowercase, no extra spaces, minimal special chars)

    Examples:
        >>> normalize_title("  Samsung  Galaxy  S24  ")
        "samsung galaxy s24"
        >>> normalize_title("iPhone 15 Pro (256GB)")
        "iphone 15 pro 256gb"
    """
    if not title:
        return ""

    normalized = title.lower()

    normalized = re.sub(r"\s+", " ", normalized).strip()

    normalized = re.sub(r"[^\w\s\-]", "", normalized)

    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def is_similar_url(url1: str, url2: str, threshold: float = 0.8) -> bool:
    """
    Check if two URLs are similar (same domain and similar path).

    Args:
        url1: First URL
        url2: Second URL
        threshold: Similarity threshold (0.0-1.0)

    Returns:
        True if URLs are similar, False otherwise

    Examples:
        >>> is_similar_url(
        ...     "https://coupang.com/vp/products/123",
        ...     "https://coupang.com/vp/products/123?ref=abc"
        ... )
        True
        >>> is_similar_url(
        ...     "https://coupang.com/vp/products/123",
        ...     "https://naver.com/vp/products/123"
        ... )
        False
    """
    try:
        parsed1 = urlparse(url1)
        parsed2 = urlparse(url2)

        if parsed1.netloc != parsed2.netloc:
            return False

        path1 = parsed1.path
        path2 = parsed2.path

        if path1 == path2:
            return True

        ratio = SequenceMatcher(None, path1, path2).ratio()
        return ratio >= threshold

    except Exception:
        return False


def validate_price_range(
    price: Optional[int],
    min_price: int = 100,
    max_price: int = 1_000_000_000,
) -> bool:
    """
    Validate if price is within acceptable range.

    Args:
        price: Price to validate (in KRW)
        min_price: Minimum acceptable price (default: 100 KRW)
        max_price: Maximum acceptable price (default: 1 billion KRW)

    Returns:
        True if price is valid, False otherwise

    Examples:
        >>> validate_price_range(10000)
        True
        >>> validate_price_range(50)  # Below minimum
        False
        >>> validate_price_range(2_000_000_000)  # Above maximum
        False
    """
    if price is None:
        return True  # None is acceptable (optional field)

    return min_price <= price <= max_price


def validate_discount_rate(discount_rate: Optional[float]) -> bool:
    """
    Validate if discount rate is within acceptable range (0.0 - 1.0).

    Args:
        discount_rate: Discount rate as decimal (0.0 = 0%, 1.0 = 100%)

    Returns:
        True if discount rate is valid, False otherwise

    Examples:
        >>> validate_discount_rate(0.25)  # 25% discount
        True
        >>> validate_discount_rate(1.0)  # 100% discount
        True
        >>> validate_discount_rate(1.5)  # Invalid
        False
        >>> validate_discount_rate(-0.1)  # Invalid
        False
    """
    if discount_rate is None:
        return True  # None is acceptable (optional field)

    return 0.0 <= discount_rate <= 1.0


def validate_url_format(url: Optional[str]) -> bool:
    """
    Validate if URL has valid format.

    Args:
        url: URL to validate

    Returns:
        True if URL is valid, False otherwise

    Examples:
        >>> validate_url_format("https://coupang.com/vp/products/123")
        True
        >>> validate_url_format("not-a-url")
        False
        >>> validate_url_format("")
        False
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url)
        # Must have scheme and netloc
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


def detect_duplicate_articles(
    title1: str,
    url1: str,
    title2: str,
    url2: str,
    title_threshold: float = 0.85,
    url_threshold: float = 0.8,
) -> bool:
    norm_title1 = normalize_title(title1)
    norm_title2 = normalize_title(title2)

    title_ratio = SequenceMatcher(None, norm_title1, norm_title2).ratio()
    if title_ratio < title_threshold:
        return False

    return is_similar_url(url1, url2, url_threshold)


def detect_duplicate_products(
    title1: str,
    url1: str,
    title2: str,
    url2: str,
    title_threshold: float = 0.85,
    url_threshold: float = 0.8,
) -> bool:
    """
    Detect if two products are duplicates based on title and URL similarity.

    Args:
        title1: First product title
        url1: First product URL
        title2: Second product title
        url2: Second product URL
        title_threshold: Title similarity threshold
        url_threshold: URL similarity threshold

    Returns:
        True if products are likely duplicates, False otherwise

    Examples:
        >>> detect_duplicate_products(
        ...     "Samsung Galaxy S24",
        ...     "https://coupang.com/vp/products/123",
        ...     "Samsung Galaxy S24",
        ...     "https://coupang.com/vp/products/123?ref=abc"
        ... )
        True
    """
    return detect_duplicate_articles(
        title1,
        url1,
        title2,
        url2,
        title_threshold=title_threshold,
        url_threshold=url_threshold,
    )


def _get_value(article: Any, *keys: str) -> Any:
    if isinstance(article, dict):
        for key in keys:
            if key in article:
                return article[key]
        return None

    for key in keys:
        if hasattr(article, key):
            return getattr(article, key)
    return None


def validate_article(article: Any) -> tuple[bool, list[str]]:
    errors: list[str] = []

    title = _get_value(article, "title")
    link = _get_value(article, "link", "url")
    summary = _get_value(article, "summary", "category")
    source = _get_value(article, "source", "source_id", "source_name")
    category = _get_value(article, "category", "platform")

    current_price = _get_value(article, "current_price")
    avg_price = _get_value(article, "avg_price")
    list_price = _get_value(article, "list_price")
    discount_rate = _get_value(article, "discount_rate")

    if not title or not isinstance(title, str):
        errors.append("title is missing or not a string")
    elif len(title.strip()) == 0:
        errors.append("title is empty")

    if not link or not isinstance(link, str):
        errors.append("link is missing or not a string")
    elif not validate_url_format(link):
        errors.append(f"link has invalid URL format: {link}")

    if not summary or not isinstance(summary, str):
        errors.append("summary is missing or not a string")
    elif len(summary.strip()) == 0:
        errors.append("summary is empty")

    if not source or not isinstance(source, str):
        errors.append("source is missing or not a string")

    if not category or not isinstance(category, str):
        errors.append("category is missing or not a string")

    if not validate_price_range(current_price):
        errors.append(f"current_price out of range: {current_price}")
    if not validate_price_range(avg_price):
        errors.append(f"avg_price out of range: {avg_price}")
    if not validate_price_range(list_price):
        errors.append(f"list_price out of range: {list_price}")
    if not validate_discount_rate(discount_rate):
        errors.append(f"discount_rate out of range: {discount_rate}")

    return len(errors) == 0, errors
