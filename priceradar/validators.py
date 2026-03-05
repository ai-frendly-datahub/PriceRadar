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
from typing import Optional
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


def validate_url_format(url: str) -> bool:
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
    # Normalize titles
    norm_title1 = normalize_title(title1)
    norm_title2 = normalize_title(title2)

    # Check title similarity
    title_ratio = SequenceMatcher(None, norm_title1, norm_title2).ratio()
    if title_ratio < title_threshold:
        return False

    # Check URL similarity
    return is_similar_url(url1, url2, url_threshold)
