"""Unit tests for priceradar.reporters.html_reporter module."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from priceradar.reporters.html_reporter import HtmlReporter


@pytest.mark.unit
def test_html_reporter_initializes_with_default_template_dir() -> None:
    """HtmlReporter initializes with default template directory."""
    reporter = HtmlReporter()
    assert reporter.template_dir == "priceradar/reporters/templates"


@pytest.mark.unit
def test_html_reporter_initializes_with_custom_template_dir() -> None:
    """HtmlReporter initializes with custom template directory."""
    custom_dir = "/custom/templates"
    reporter = HtmlReporter(template_dir=custom_dir)
    assert reporter.template_dir == custom_dir


@pytest.mark.unit
def test_html_reporter_handles_nonexistent_template_dir() -> None:
    """HtmlReporter handles nonexistent template directory gracefully."""
    reporter = HtmlReporter(template_dir="/nonexistent/path")
    assert reporter.env is None


@pytest.mark.unit
def test_generate_report_creates_output_file() -> None:
    """generate_report creates output file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals: list[dict[str, Any]] = []
        result = reporter.generate_report(deals, output_path)

        assert result == output_path
        assert os.path.exists(output_path)


@pytest.mark.unit
def test_generate_report_returns_correct_path() -> None:
    """generate_report returns the output path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "test_report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals: list[dict[str, Any]] = []
        result = reporter.generate_report(deals, output_path)

        assert result == output_path


@pytest.mark.unit
def test_generate_report_creates_parent_directories() -> None:
    """generate_report creates parent directories if they don't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "nested", "dir", "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals: list[dict[str, Any]] = []
        reporter.generate_report(deals, output_path)

        assert os.path.exists(output_path)
        assert os.path.isdir(os.path.dirname(output_path))


@pytest.mark.unit
def test_generate_report_with_single_deal() -> None:
    """generate_report handles single deal correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals = [
            {
                "product_id": "prod_001",
                "title": "Test Product",
                "url": "https://example.com/product",
                "category": "Electronics",
                "platform": "coupang",
                "current_price": 50000,
                "avg_price": 60000,
                "saving_amount": 10000,
                "radar_score": 0.85,
                "discount_rate": 0.167,
                "explanation": "Good deal",
            }
        ]

        result = reporter.generate_report(deals, output_path)
        assert os.path.exists(result)

        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
            assert "Test Product" in content
            assert "50000" in content
            assert "Electronics" in content


@pytest.mark.unit
def test_generate_report_with_multiple_deals() -> None:
    """generate_report handles multiple deals correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals = [
            {
                "product_id": f"prod_{i:03d}",
                "title": f"Product {i}",
                "url": f"https://example.com/product/{i}",
                "category": "Electronics",
                "platform": "coupang",
                "current_price": 50000 + i * 1000,
                "radar_score": 0.5 + i * 0.1,
            }
            for i in range(5)
        ]

        result = reporter.generate_report(deals, output_path)
        assert os.path.exists(result)

        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
            assert "Product 0" in content
            assert "Product 4" in content


@pytest.mark.unit
def test_generate_report_with_missing_optional_fields() -> None:
    """generate_report handles deals with missing optional fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals = [
            {
                "product_id": "prod_001",
                "title": "Minimal Product",
                "url": "https://example.com/product",
            }
        ]

        result = reporter.generate_report(deals, output_path)
        assert os.path.exists(result)

        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
            assert "Minimal Product" in content


@pytest.mark.unit
def test_generate_report_includes_html_structure() -> None:
    """Generated report includes proper HTML structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals: list[dict[str, Any]] = []
        reporter.generate_report(deals, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "<!DOCTYPE html>" in content
            assert "<html" in content
            assert "</html>" in content
            assert "<head>" in content
            assert "<body>" in content


@pytest.mark.unit
def test_generate_report_includes_custom_title() -> None:
    """Generated report includes custom title."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        custom_title = "Custom Report Title"
        deals: list[dict[str, Any]] = []
        reporter.generate_report(deals, output_path, title=custom_title)

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert custom_title in content


@pytest.mark.unit
def test_generate_report_with_empty_deals_list() -> None:
    """generate_report handles empty deals list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals: list[dict[str, Any]] = []
        result = reporter.generate_report(deals, output_path)

        assert os.path.exists(result)
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
            assert "<!DOCTYPE html>" in content


@pytest.mark.unit
def test_generate_report_with_none_optional_fields() -> None:
    """generate_report handles None values in optional fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals = [
            {
                "title": "Product",
                "url": "https://example.com",
                "category": None,
                "platform": None,
                "avg_price": None,
                "saving_amount": None,
            }
        ]
        result = reporter.generate_report(deals, output_path)

        assert os.path.exists(result)


@pytest.mark.unit
def test_generate_report_with_special_characters() -> None:
    """generate_report handles special characters in data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals = [
            {
                "title": 'Product with "quotes" & <special> chars',
                "url": "https://example.com?param=value&other=123",
            }
        ]
        result = reporter.generate_report(deals, output_path)

        assert os.path.exists(result)
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
            assert len(content) > 0


@pytest.mark.unit
def test_generate_report_file_is_valid_html() -> None:
    """Generated report file is valid HTML."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals: list[dict[str, Any]] = []
        reporter.generate_report(deals, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert content.count("<") > 0
            assert content.count(">") > 0
            assert content.count("</") > 0


@pytest.mark.unit
def test_generate_report_file_encoding_is_utf8() -> None:
    """Generated report file uses UTF-8 encoding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals = [{"title": "한글 테스트"}]
        reporter.generate_report(deals, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "한글 테스트" in content


@pytest.mark.unit
def test_generate_report_file_size_reasonable() -> None:
    """Generated report file has reasonable size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "report.html")
        reporter = HtmlReporter(template_dir="/nonexistent")

        deals = [{"title": f"Product {i}"} for i in range(10)]
        reporter.generate_report(deals, output_path)

        file_size = os.path.getsize(output_path)
        assert file_size > 1000


@pytest.mark.unit
def test_generate_report_with_template_directory() -> None:
    """generate_report uses Jinja2 template when template directory exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create template directory and template file
        template_dir = os.path.join(tmpdir, "templates")
        os.makedirs(template_dir)

        # Create a minimal report.html template
        template_content = """
        <!DOCTYPE html>
        <html>
        <head><title>{{ title }}</title></head>
        <body>
        <h1>{{ title }}</h1>
        <p>Generated: {{ generated_at }}</p>
        <p>Total deals: {{ total_deals }}</p>
        {% for deal in deals %}
        <div>{{ deal.title }}</div>
        {% endfor %}
        </body>
        </html>
        """

        with open(os.path.join(template_dir, "report.html"), "w") as f:
            f.write(template_content)

        # Create reporter with template directory
        reporter = HtmlReporter(template_dir=template_dir)

        output_path = os.path.join(tmpdir, "report.html")
        deals = [
            {"title": "Deal 1", "url": "https://example.com/1"},
            {"title": "Deal 2", "url": "https://example.com/2"},
        ]

        result = reporter.generate_report(deals, output_path, title="Test Report")

        assert os.path.exists(result)
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
            assert "Test Report" in content
            assert "Total deals: 2" in content


@pytest.mark.unit
def test_generate_basic_html_with_categories_and_platforms() -> None:
    """_generate_basic_html extracts and displays categories and platforms."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "Product 1",
            "url": "https://example.com/1",
            "category": "Electronics",
            "platform": "coupang",
        },
        {
            "title": "Product 2",
            "url": "https://example.com/2",
            "category": "Fashion",
            "platform": "gmarket",
        },
        {
            "title": "Product 3",
            "url": "https://example.com/3",
            "category": "Electronics",
            "platform": "coupang",
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    assert "Electronics" in html
    assert "Fashion" in html
    assert "coupang" in html
    assert "gmarket" in html
    assert 'id="categoryFilter"' in html
    assert 'id="platformFilter"' in html


@pytest.mark.unit
def test_generate_basic_html_score_bar_calculation() -> None:
    """_generate_basic_html calculates score bar width correctly."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "High Score Product",
            "url": "https://example.com/1",
            "radar_score": 0.95,
        },
        {
            "title": "Low Score Product",
            "url": "https://example.com/2",
            "radar_score": 0.25,
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    # Score 0.95 should result in 95% width
    assert 'style="width: 95%"' in html
    # Score 0.25 should result in 25% width
    assert 'style="width: 25%"' in html


@pytest.mark.unit
def test_generate_basic_html_with_discount_rate() -> None:
    """_generate_basic_html displays discount rate when present."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "Discounted Product",
            "url": "https://example.com/1",
            "discount_rate": 0.30,
            "radar_score": 0.8,
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    # 30% discount should be displayed
    assert "30%" in html


@pytest.mark.unit
def test_generate_basic_html_with_explanation() -> None:
    """_generate_basic_html includes explanation text when provided."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "Product with Explanation",
            "url": "https://example.com/1",
            "explanation": "This is a great deal because of X and Y",
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    assert "This is a great deal because of X and Y" in html
    assert 'class="explanation"' in html


@pytest.mark.unit
def test_generate_basic_html_with_price_and_savings() -> None:
    """_generate_basic_html displays price and savings information."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "Product",
            "url": "https://example.com/1",
            "current_price": 50000,
            "avg_price": 60000,
            "saving_amount": 10000,
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    assert "50,000원" in html
    assert "60,000원" in html
    assert "10,000원" in html


@pytest.mark.unit
def test_generate_basic_html_badges_for_category_and_platform() -> None:
    """_generate_basic_html renders category and platform badges."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "Product",
            "url": "https://example.com/1",
            "category": "Electronics",
            "platform": "coupang",
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    assert 'class="badge badge-category"' in html
    assert 'class="badge badge-platform"' in html
    assert "Electronics" in html
    assert "coupang" in html


@pytest.mark.unit
def test_generate_basic_html_javascript_functions() -> None:
    """_generate_basic_html includes JavaScript filter and sort functions."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals: list[dict[str, Any]] = []
    html = reporter._generate_basic_html(deals, "Test Report")

    assert "function filterDeals()" in html
    assert "function sortDeals()" in html
    assert "function resetFilters()" in html
    assert "categoryFilter" in html
    assert "platformFilter" in html
    assert "sortBy" in html


@pytest.mark.unit
def test_generate_basic_html_with_missing_category() -> None:
    """_generate_basic_html handles missing category with default value."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "Product without category",
            "url": "https://example.com/1",
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    # Should have default category "기타"
    assert "기타" in html


@pytest.mark.unit
def test_generate_basic_html_statistics_section() -> None:
    """_generate_basic_html includes statistics section with counts."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "Product 1",
            "url": "https://example.com/1",
            "category": "Electronics",
            "platform": "coupang",
        },
        {
            "title": "Product 2",
            "url": "https://example.com/2",
            "category": "Fashion",
            "platform": "gmarket",
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    # Should show 2 total products
    assert "총 상품" in html
    # Should show 2 categories
    assert "카테고리" in html
    # Should show 2 platforms
    assert "플랫폼" in html


@pytest.mark.unit
def test_generate_basic_html_includes_chart_js_cdn() -> None:
    """_generate_basic_html includes Chart.js CDN link."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals: list[dict[str, Any]] = []
    html = reporter._generate_basic_html(deals, "Test Report")

    assert "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js" in html


@pytest.mark.unit
def test_generate_basic_html_includes_chart_canvas_elements() -> None:
    """_generate_basic_html includes three chart canvas elements."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "Product 1",
            "url": "https://example.com/1",
            "category": "Electronics",
            "current_price": 50000,
            "radar_score": 0.85,
            "discount_rate": 0.15,
        },
        {
            "title": "Product 2",
            "url": "https://example.com/2",
            "category": "Fashion",
            "current_price": 30000,
            "radar_score": 0.75,
            "discount_rate": 0.20,
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    # Check for all three chart canvas elements
    assert 'id="categoryPriceChart"' in html
    assert 'id="discountDistributionChart"' in html
    assert 'id="scoreVsCategoryChart"' in html


@pytest.mark.unit
def test_generate_basic_html_includes_deals_json_data() -> None:
    """_generate_basic_html includes deals data as JSON."""
    reporter = HtmlReporter(template_dir="/nonexistent")

    deals = [
        {
            "title": "Product 1",
            "url": "https://example.com/1",
            "category": "Electronics",
            "current_price": 50000,
            "radar_score": 0.85,
        },
    ]

    html = reporter._generate_basic_html(deals, "Test Report")

    # Check for JSON data script tag
    assert 'id="deals-data"' in html
    assert 'type="application/json"' in html
    assert "Product 1" in html
