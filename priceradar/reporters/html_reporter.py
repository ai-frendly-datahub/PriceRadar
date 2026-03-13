"""
HTML Reporter - Jinja2 기반 가격 레이다 리포트 생성
"""

import json
import os
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from priceradar.forecasting.price_forecast import forecast_category_prices
from priceradar.models import Deal


class HtmlReporter:
    """HTML 리포트 생성기"""

    def __init__(self, template_dir: str = "priceradar/reporters/templates") -> None:
        """
        Args:
            template_dir: Jinja2 템플릿 디렉터리
        """
        self.template_dir = template_dir

        # Jinja2 환경 설정
        if os.path.exists(template_dir):
            self.env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=select_autoescape(["html", "xml"]),
            )
        else:
            # 템플릿 디렉터리가 없으면 기본 템플릿 사용
            self.env = None

    def generate_report(
        self,
        deals: list[dict[str, Any]],
        output_path: str,
        title: str = "PriceRadar 일일 리포트",
    ) -> str:
        """
        가격 딜 리포트 HTML 생성

        Args:
            deals: 상위 딜 리스트 (get_top_deals 결과)
            output_path: 출력 파일 경로
            title: 리포트 제목

        Returns:
            생성된 HTML 파일 경로
        """
        # 출력 디렉터리 생성
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        forecast_data = self._build_forecast_data(deals)

        # 템플릿이 없으면 기본 HTML 생성
        if not self.env:
            html_content = self._generate_basic_html(deals, title, forecast_data)
        else:
            template = self.env.get_template("report.html")
            html_content = template.render(
                title=title,
                generated_at=datetime.now(tz=UTC),
                deals=deals,
                total_deals=len(deals),
                forecast_data=forecast_data,
            )

        # 파일 저장
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_path

    def _generate_basic_html(
        self,
        deals: list[dict[str, Any]],
        title: str,
        forecast_data: dict[str, dict[str, list[Any]]] | None = None,
    ) -> str:
        """기본 HTML 템플릿 (Jinja2 없이)"""
        now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        normalized_forecast_data = forecast_data or {}
        history_data = self._build_forecast_history(deals, set(normalized_forecast_data.keys()))

        # 카테고리 및 플랫폼 목록 추출
        categories = sorted(set(deal.get("category", "기타") for deal in deals))
        platforms = sorted(
            set(deal.get("platform", "기타") for deal in deals if deal.get("platform"))
        )

        html_parts = [
            "<!DOCTYPE html>",
            '<html lang="ko">',
            "<head>",
            '    <meta charset="UTF-8">',
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f"    <title>{title}</title>",
            "    <style>",
            "        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }",
            "        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; }",
            "        h1 { color: #333; border-bottom: 3px solid #007bff; padding-bottom: 10px; }",
            "        .meta { color: #666; margin-bottom: 20px; }",
            "        .filters { background: #e9ecef; padding: 15px; border-radius: 8px; margin-bottom: 20px; }",
            "        .filters label { font-weight: bold; margin-right: 10px; }",
            "        .filters select { padding: 8px; border-radius: 4px; border: 1px solid #ccc; margin-right: 20px; min-width: 150px; }",
            "        .filters button { padding: 8px 16px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }",
            "        .filters button:hover { background: #0056b3; }",
            "        .stats { display: flex; gap: 20px; margin-bottom: 20px; }",
            "        .stat-box { flex: 1; background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; }",
            "        .stat-value { font-size: 24px; font-weight: bold; color: #007bff; }",
            "        .stat-label { color: #666; font-size: 14px; margin-top: 5px; }",
            "        .deal-card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 15px; background: #fafafa; }",
            "        .deal-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.1); }",
            "        .deal-card.hidden { display: none; }",
            "        .deal-title { font-size: 18px; font-weight: bold; color: #222; margin-bottom: 8px; }",
            "        .deal-price { font-size: 24px; color: #e74c3c; font-weight: bold; }",
            "        .deal-meta { color: #666; font-size: 14px; margin-top: 8px; }",
            "        .score-bar { height: 8px; background: #ddd; border-radius: 4px; overflow: hidden; margin-top: 10px; }",
            "        .score-fill { height: 100%; background: linear-gradient(90deg, #28a745, #ffc107, #dc3545); }",
            "        .explanation { color: #555; margin-top: 10px; font-style: italic; }",
            "        .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; margin-right: 5px; }",
            "        .badge-category { background: #007bff; color: white; }",
            "        .badge-platform { background: #6c757d; color: white; }",
            "        .charts-section { margin-top: 24px; }",
            "        .chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; }",
            "        .chart-card { flex: 1; background: #f8f9fa; padding: 15px; border-radius: 8px; }",
            "        .chart-card h3 { margin-top: 0; color: #333; }",
            "        .chart-card canvas { max-height: 300px; }",
            "        .forecast-card { margin-top: 20px; }",
            "        #priceForecastChart { width: 100%; min-height: 360px; }",
            "        .forecast-empty { color: #6c757d; padding: 10px 0; }",
            "    </style>",
            "</head>",
            "<body>",
            '    <div class="container">',
            f"        <h1>{title}</h1>",
            f'        <div class="meta">생성일시: {now} | 총 {len(deals)}개 딜</div>',
            "",
            "        <!-- 통계 -->",
            '        <div class="stats">',
            '            <div class="stat-box">',
            f'                <div class="stat-value">{len(deals)}</div>',
            '                <div class="stat-label">총 상품</div>',
            "            </div>",
            '            <div class="stat-box">',
            f'                <div class="stat-value">{len(categories)}</div>',
            '                <div class="stat-label">카테고리</div>',
            "            </div>",
            '            <div class="stat-box">',
            f'                <div class="stat-value">{len(platforms)}</div>',
            '                <div class="stat-label">플랫폼</div>',
            "            </div>",
            "        </div>",
            "",
            "        <!-- 필터 -->",
            '        <div class="filters">',
            '            <label for="categoryFilter">카테고리:</label>',
            '            <select id="categoryFilter" onchange="filterDeals()">',
            '                <option value="all">전체</option>',
        ]

        # 카테고리 옵션 추가
        for cat in categories:
            html_parts.append(f'                <option value="{cat}">{cat}</option>')

        html_parts.extend(
            [
                "            </select>",
                '            <label for="platformFilter">플랫폼:</label>',
                '            <select id="platformFilter" onchange="filterDeals()">',
                '                <option value="all">전체</option>',
            ]
        )

        # 플랫폼 옵션 추가
        for plat in platforms:
            html_parts.append(f'                <option value="{plat}">{plat}</option>')

        html_parts.extend(
            [
                "            </select>",
                '            <label for="sortBy">정렬:</label>',
                '            <select id="sortBy" onchange="sortDeals()">',
                '                <option value="score">점수 높은순</option>',
                '                <option value="price_low">가격 낮은순</option>',
                '                <option value="price_high">가격 높은순</option>',
                '                <option value="discount">할인율 높은순</option>',
                "            </select>",
                '            <button onclick="resetFilters()">초기화</button>',
                "        </div>",
                "",
                '        <div id="dealsContainer">',
            ]
        )

        # 딜 카드 생성
        for idx, deal in enumerate(deals):
            _ = deal.get("product_id", "")
            title_text = deal.get("title", "제목 없음")
            url = deal.get("url", "#")
            category = deal.get("category", "기타")
            platform = deal.get("platform", "기타")
            current_price = deal.get("current_price", 0)
            avg_price = deal.get("avg_price")
            saving_amount = deal.get("saving_amount")
            radar_score = deal.get("radar_score", 0.0)
            discount_rate = deal.get("discount_rate", 0.0)
            explanation = deal.get("explanation", "")

            # 점수 바 너비 계산
            score_width = int(radar_score * 100)

            html_parts.extend(
                [
                    f'        <div class="deal-card" data-category="{category}" data-platform="{platform}" data-price="{current_price}" data-score="{radar_score}" data-discount="{discount_rate}" data-index="{idx}">',
                    f'            <div class="deal-title"><a href="{url}" target="_blank">{title_text}</a></div>',
                ]
            )

            if category:
                html_parts.append(
                    f'            <span class="badge badge-category">{category}</span>'
                )
            if platform:
                html_parts.append(
                    f'            <span class="badge badge-platform">{platform}</span>'
                )

            html_parts.append(f'            <div class="deal-price">{current_price:,}원</div>')

            if avg_price and saving_amount:
                html_parts.append(
                    f'            <div class="deal-meta">평균가: {avg_price:,}원 | 절약: {saving_amount:,}원</div>'
                )

            html_parts.extend(
                [
                    f'            <div class="score-bar"><div class="score-fill" style="width: {score_width}%"></div></div>',
                    f'            <div class="deal-meta">레이다 점수: {radar_score:.2f}',
                ]
            )

            if discount_rate > 0:
                html_parts.append(f" | 할인율: {int(discount_rate * 100)}%")

            html_parts.append("</div>")

            if explanation:
                html_parts.append(f'            <div class="explanation">{explanation}</div>')

            html_parts.append("        </div>")

        html_parts.extend(
            [
                "        </div>",  # dealsContainer
                "",
                "        <!-- Charts Section -->",
                '        <div class="charts-section">',
                "            <h2>분석 차트</h2>",
                '            <div class="chart-grid">',
                '                <div class="chart-card">',
                "                    <h3>카테고리별 평균 가격</h3>",
                '                    <canvas id="categoryPriceChart"></canvas>',
                "                </div>",
                '                <div class="chart-card">',
                "                    <h3>할인율 분포</h3>",
                '                    <canvas id="discountDistributionChart"></canvas>',
                "                </div>",
                '                <div class="chart-card">',
                "                    <h3>카테고리별 평균 점수</h3>",
                '                    <canvas id="scoreVsCategoryChart"></canvas>',
                "                </div>",
                "            </div>",
                "        </div>",
                "",
                "        <!-- Forecast Section -->",
                '        <div class="charts-section">',
                "            <h2>Price Forecasts (14-day ahead)</h2>",
                '            <div class="chart-card forecast-card">',
                '                <div id="priceForecastChart"></div>',
                "            </div>",
                "        </div>",
                "",
                "        <!-- Deals Data -->",
                '        <script id="deals-data" type="application/json">',
            ]
        )

        # Serialize deals to JSON
        deals_json = json.dumps(
            deals, default=lambda o: o.isoformat() if isinstance(o, (datetime, date)) else str(o)
        )
        html_parts.append(deals_json)
        html_parts.append("        </script>")

        forecast_payload: dict[str, dict[str, list[Any]]] = {}
        for category, payload in normalized_forecast_data.items():
            category_history = history_data.get(
                category,
                {
                    "history_dates": [],
                    "history_avg": [],
                },
            )
            forecast_payload[category] = {
                "dates": payload.get("dates", []),
                "forecast": payload.get("forecast", []),
                "lower_80": payload.get("lower_80", []),
                "upper_80": payload.get("upper_80", []),
                "lower_95": payload.get("lower_95", []),
                "upper_95": payload.get("upper_95", []),
                "history_dates": category_history.get("history_dates", []),
                "history_avg": category_history.get("history_avg", []),
            }

        forecast_json = json.dumps(forecast_payload, ensure_ascii=False)
        html_parts.extend(
            [
                "",
                "        <!-- Forecast Data -->",
                '        <script id="forecast-data" type="application/json">',
                forecast_json,
                "        </script>",
            ]
        )

        html_parts.extend(
            [
                "",
                "        <!-- Chart.js Library -->",
                '        <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>',
                "        <!-- Plotly Library -->",
                '        <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>',
                "",
                "        <!-- JavaScript -->",
                "        <script>",
                "            function readJson(id, fallback) {",
                "                const elem = document.getElementById(id);",
                "                if (!elem) return fallback;",
                "                try {",
                "                    return JSON.parse(elem.textContent);",
                "                } catch (e) {",
                "                    return fallback;",
                "                }",
                "            }",
                "",
                "            function palette(n) {",
                "                const colors = [",
                "                    '#007bff', '#28a745', '#dc3545', '#ffc107', '#17a2b8',",
                "                    '#6f42c1', '#e83e8c', '#fd7e14', '#20c997', '#6c757d'",
                "                ];",
                "                return colors[n % colors.length];",
                "            }",
                "",
                "            const deals = readJson('deals-data', []);",
                "            const forecastData = readJson('forecast-data', {});",
                "",
                "            // Category Price Bar Chart",
                "            if (deals.length > 0) {",
                "                const categoryPrices = {};",
                "                deals.forEach(deal => {",
                "                    const cat = deal.category || '기타';",
                "                    if (!categoryPrices[cat]) {",
                "                        categoryPrices[cat] = { sum: 0, count: 0 };",
                "                    }",
                "                    categoryPrices[cat].sum += deal.current_price || 0;",
                "                    categoryPrices[cat].count += 1;",
                "                });",
                "",
                "                const catLabels = Object.keys(categoryPrices).sort();",
                "                const catData = catLabels.map(cat => categoryPrices[cat].sum / categoryPrices[cat].count);",
                "                const catColors = catLabels.map((_, i) => palette(i));",
                "",
                "                new Chart(document.getElementById('categoryPriceChart'), {",
                "                    type: 'bar',",
                "                    data: {",
                "                        labels: catLabels,",
                "                        datasets: [{",
                "                            label: '평균 가격 (원)',",
                "                            data: catData,",
                "                            backgroundColor: catColors,",
                "                            borderColor: catColors,",
                "                            borderWidth: 1",
                "                        }]",
                "                    },",
                "                    options: {",
                "                        responsive: true,",
                "                        maintainAspectRatio: true,",
                "                        plugins: {",
                "                            legend: { display: true }",
                "                        },",
                "                        scales: {",
                "                            y: { beginAtZero: true }",
                "                        }",
                "                    }",
                "                });",
                "",
                "                // Discount Distribution Bar Chart",
                "                const discountBuckets = {};",
                "                for (let i = 0; i <= 100; i += 10) {",
                "                    discountBuckets[i] = 0;",
                "                }",
                "                deals.forEach(deal => {",
                "                    const rate = (deal.discount_rate || 0) * 100;",
                "                    const bucket = Math.floor(rate / 10) * 10;",
                "                    if (bucket <= 100) {",
                "                        discountBuckets[bucket] = (discountBuckets[bucket] || 0) + 1;",
                "                    }",
                "                });",
                "",
                "                const discountLabels = Object.keys(discountBuckets).map(k => k + '%');",
                "                const discountData = Object.values(discountBuckets);",
                "",
                "                new Chart(document.getElementById('discountDistributionChart'), {",
                "                    type: 'bar',",
                "                    data: {",
                "                        labels: discountLabels,",
                "                        datasets: [{",
                "                            label: '상품 수',",
                "                            data: discountData,",
                "                            backgroundColor: '#ffc107',",
                "                            borderColor: '#ffc107',",
                "                            borderWidth: 1",
                "                        }]",
                "                    },",
                "                    options: {",
                "                        responsive: true,",
                "                        maintainAspectRatio: true,",
                "                        plugins: {",
                "                            legend: { display: true }",
                "                        },",
                "                        scales: {",
                "                            y: { beginAtZero: true }",
                "                        }",
                "                    }",
                "                });",
                "",
                "                // Score vs Category Bar Chart",
                "                const categoryScores = {};",
                "                deals.forEach(deal => {",
                "                    const cat = deal.category || '기타';",
                "                    if (!categoryScores[cat]) {",
                "                        categoryScores[cat] = { sum: 0, count: 0 };",
                "                    }",
                "                    categoryScores[cat].sum += deal.radar_score || 0;",
                "                    categoryScores[cat].count += 1;",
                "                });",
                "",
                "                const scoreLabels = Object.keys(categoryScores).sort();",
                "                const scoreData = scoreLabels.map(cat => categoryScores[cat].sum / categoryScores[cat].count);",
                "                const scoreColors = scoreLabels.map((_, i) => palette(i + 5));",
                "",
                "                new Chart(document.getElementById('scoreVsCategoryChart'), {",
                "                    type: 'bar',",
                "                    data: {",
                "                        labels: scoreLabels,",
                "                        datasets: [{",
                "                            label: '평균 점수',",
                "                            data: scoreData,",
                "                            backgroundColor: scoreColors,",
                "                            borderColor: scoreColors,",
                "                            borderWidth: 1",
                "                        }]",
                "                    },",
                "                    options: {",
                "                        responsive: true,",
                "                        maintainAspectRatio: true,",
                "                        plugins: {",
                "                            legend: { display: true }",
                "                        },",
                "                        scales: {",
                "                            y: { beginAtZero: true, max: 1 }",
                "                        }",
                "                    }",
                "                });",
                "            }",
                "",
                "            const forecastCategories = Object.keys(forecastData);",
                "            if (forecastCategories.length > 0 && typeof Plotly !== 'undefined') {",
                "                const traces = [];",
                "                const layout = {",
                "                    height: Math.max(420, forecastCategories.length * 240),",
                "                    showlegend: true,",
                "                    legend: { orientation: 'h', x: 0, y: 1.08 },",
                "                    margin: { l: 60, r: 20, t: 24, b: 40 },",
                "                    paper_bgcolor: '#f8f9fa',",
                "                    plot_bgcolor: '#ffffff'",
                "                };",
                "",
                "                forecastCategories.forEach((category, index) => {",
                "                    const axisId = index + 1;",
                "                    const axisSuffix = axisId === 1 ? '' : String(axisId);",
                "                    const xAxisName = axisId === 1 ? 'x' : `x${axisId}`;",
                "                    const yAxisName = axisId === 1 ? 'y' : `y${axisId}`;",
                "                    const item = forecastData[category] || {};",
                "                    const historyDates = item.history_dates || [];",
                "                    const historyAvg = item.history_avg || [];",
                "                    const dates = item.dates || [];",
                "                    const forecast = item.forecast || [];",
                "                    const lower80 = item.lower_80 || [];",
                "                    const upper80 = item.upper_80 || [];",
                "                    const lower95 = item.lower_95 || [];",
                "                    const upper95 = item.upper_95 || [];",
                "                    const showLegend = index === 0;",
                "",
                "                    traces.push({",
                "                        x: dates,",
                "                        y: upper95,",
                "                        mode: 'lines',",
                "                        line: { color: 'rgba(255, 165, 0, 0)' },",
                "                        hoverinfo: 'skip',",
                "                        showlegend: false,",
                "                        xaxis: xAxisName,",
                "                        yaxis: yAxisName",
                "                    });",
                "                    traces.push({",
                "                        x: dates,",
                "                        y: lower95,",
                "                        mode: 'lines',",
                "                        line: { color: 'rgba(255, 165, 0, 0)' },",
                "                        fill: 'tonexty',",
                "                        fillcolor: 'rgba(255, 165, 0, 0.12)',",
                "                        name: '95% CI',",
                "                        showlegend: showLegend,",
                "                        xaxis: xAxisName,",
                "                        yaxis: yAxisName",
                "                    });",
                "",
                "                    traces.push({",
                "                        x: dates,",
                "                        y: upper80,",
                "                        mode: 'lines',",
                "                        line: { color: 'rgba(255, 165, 0, 0)' },",
                "                        hoverinfo: 'skip',",
                "                        showlegend: false,",
                "                        xaxis: xAxisName,",
                "                        yaxis: yAxisName",
                "                    });",
                "                    traces.push({",
                "                        x: dates,",
                "                        y: lower80,",
                "                        mode: 'lines',",
                "                        line: { color: 'rgba(255, 165, 0, 0)' },",
                "                        fill: 'tonexty',",
                "                        fillcolor: 'rgba(255, 165, 0, 0.2)',",
                "                        name: '80% CI',",
                "                        showlegend: showLegend,",
                "                        xaxis: xAxisName,",
                "                        yaxis: yAxisName",
                "                    });",
                "",
                "                    traces.push({",
                "                        x: historyDates,",
                "                        y: historyAvg,",
                "                        mode: 'lines',",
                "                        line: { color: '#1f77b4', width: 2 },",
                "                        name: 'Historical avg',",
                "                        showlegend: showLegend,",
                "                        xaxis: xAxisName,",
                "                        yaxis: yAxisName",
                "                    });",
                "                    traces.push({",
                "                        x: dates,",
                "                        y: forecast,",
                "                        mode: 'lines',",
                "                        line: { color: '#ff8c00', width: 2, dash: 'dash' },",
                "                        name: 'Forecast',",
                "                        showlegend: showLegend,",
                "                        xaxis: xAxisName,",
                "                        yaxis: yAxisName",
                "                    });",
                "",
                "                    const xAxisConfig = {",
                "                        type: 'date',",
                "                        showgrid: true,",
                "                        gridcolor: '#e5e7eb',",
                "                        title: axisId === forecastCategories.length ? 'Date' : '',",
                "                        showticklabels: axisId === forecastCategories.length",
                "                    };",
                "                    if (axisId > 1) {",
                "                        xAxisConfig.matches = 'x';",
                "                    }",
                "                    layout[`xaxis${axisSuffix}`] = xAxisConfig;",
                "                    layout[`yaxis${axisSuffix}`] = {",
                "                        title: `${category} (KRW)`,",
                "                        showgrid: true,",
                "                        gridcolor: '#f1f5f9'",
                "                    };",
                "                });",
                "",
                "                Plotly.newPlot('priceForecastChart', traces, layout, {",
                "                    responsive: true,",
                "                    displayModeBar: false",
                "                });",
                "            } else {",
                "                const forecastContainer = document.getElementById('priceForecastChart');",
                "                if (forecastContainer) {",
                "                    forecastContainer.innerHTML = '<div class=\"forecast-empty\">Forecast unavailable (need at least 21 days per category).</div>';",
                "                }",
                "            }",
                "",
                "            function filterDeals() {",
                "                const categoryFilter = document.getElementById('categoryFilter').value;",
                "                const platformFilter = document.getElementById('platformFilter').value;",
                "                const cards = document.querySelectorAll('.deal-card');",
                "",
                "                let visibleCount = 0;",
                "                cards.forEach(card => {",
                "                    const category = card.dataset.category;",
                "                    const platform = card.dataset.platform;",
                "                    const matchCategory = categoryFilter === 'all' || category === categoryFilter;",
                "                    const matchPlatform = platformFilter === 'all' || platform === platformFilter;",
                "",
                "                    if (matchCategory && matchPlatform) {",
                "                        card.classList.remove('hidden');",
                "                        visibleCount++;",
                "                    } else {",
                "                        card.classList.add('hidden');",
                "                    }",
                "                });",
                "            }",
                "",
                "            function sortDeals() {",
                "                const sortBy = document.getElementById('sortBy').value;",
                "                const container = document.getElementById('dealsContainer');",
                "                const cards = Array.from(document.querySelectorAll('.deal-card'));",
                "",
                "                cards.sort((a, b) => {",
                "                    switch(sortBy) {",
                "                        case 'score':",
                "                            return parseFloat(b.dataset.score) - parseFloat(a.dataset.score);",
                "                        case 'price_low':",
                "                            return parseFloat(a.dataset.price) - parseFloat(b.dataset.price);",
                "                        case 'price_high':",
                "                            return parseFloat(b.dataset.price) - parseFloat(a.dataset.price);",
                "                        case 'discount':",
                "                            return parseFloat(b.dataset.discount) - parseFloat(a.dataset.discount);",
                "                        default:",
                "                            return parseFloat(a.dataset.index) - parseFloat(b.dataset.index);",
                "                    }",
                "                });",
                "",
                "                cards.forEach(card => container.appendChild(card));",
                "            }",
                "",
                "            function resetFilters() {",
                "                document.getElementById('categoryFilter').value = 'all';",
                "                document.getElementById('platformFilter').value = 'all';",
                "                document.getElementById('sortBy').value = 'score';",
                "                filterDeals();",
                "                sortDeals();",
                "            }",
                "        </script>",
                "    </div>",
                "</body>",
                "</html>",
            ]
        )

        return "\n".join(html_parts)

    def _build_forecast_data(self, deals: list[dict[str, Any]]) -> dict[str, dict[str, list[Any]]]:
        parsed_deals: list[Deal] = []
        for raw_deal in deals:
            parsed = self._to_deal(raw_deal)
            if parsed is not None:
                parsed_deals.append(parsed)

        if not parsed_deals:
            return {}

        result = forecast_category_prices(parsed_deals, top_n=5)
        if not isinstance(result, dict):
            return {}
        return result

    def _build_forecast_history(
        self,
        deals: list[dict[str, Any]],
        categories: set[str],
    ) -> dict[str, dict[str, list[Any]]]:
        if not categories:
            return {}

        grouped: dict[str, dict[date, list[float]]] = defaultdict(lambda: defaultdict(list))
        for raw_deal in deals:
            parsed = self._to_deal(raw_deal)
            if parsed is None or parsed.category not in categories:
                continue
            grouped[parsed.category][parsed.collected_at.date()].append(parsed.price)

        history: dict[str, dict[str, list[Any]]] = {}
        for category in sorted(grouped):
            day_map = grouped[category]
            sorted_days = sorted(day_map)
            averages: list[float] = []
            for day in sorted_days:
                day_values = day_map[day]
                averages.append(sum(day_values) / len(day_values))
            history[category] = {
                "history_dates": [day.isoformat() for day in sorted_days],
                "history_avg": averages,
            }

        return history

    def _to_deal(self, raw_deal: dict[str, Any]) -> Deal | None:
        category_value = raw_deal.get("category")
        if not isinstance(category_value, str):
            return None
        category = category_value.strip()
        if not category:
            return None

        price_value = raw_deal.get("current_price")
        if price_value is None:
            price_value = raw_deal.get("price")
        if price_value is None:
            return None
        try:
            price = float(price_value)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None

        collected_at = self._parse_datetime(raw_deal.get("collected_at") or raw_deal.get("ts"))
        if collected_at is None:
            return None

        return Deal(price=price, category=category, collected_at=collected_at)

    def _parse_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            if normalized.endswith("Z"):
                normalized = f"{normalized[:-1]}+00:00"
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                return None
        return None


def generate_index_html(report_dir: Path) -> Path:
    """Generate an index.html that lists all available report files."""
    from datetime import datetime

    report_dir.mkdir(parents=True, exist_ok=True)

    html_files = sorted(
        [f for f in report_dir.glob("*.html") if f.name != "index.html"],
        key=lambda p: p.name,
    )

    reports = []
    for html_file in html_files:
        name = html_file.stem
        display_name = name.replace("_report", "").replace("_", " ").title()
        reports.append({"filename": html_file.name, "display_name": display_name})

    generated_at = datetime.now(UTC).isoformat()

    if reports:
        cards_html = "\n    ".join(
            f'<div class="card"><a href="{r["filename"]}"><strong>{r["display_name"]}</strong></a></div>'
            for r in reports
        )
        body_content = f'<div class="reports">\n    {cards_html}\n  </div>'
    else:
        body_content = '<div class="empty">No reports available yet.</div>'

    html_content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Radar Reports</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 24px; background: #f6f8fb; color: #0f172a; }}
    h1 {{ margin: 0 0 8px 0; }}
    .muted {{ color: #475569; font-size: 13px; margin-bottom: 24px; }}
    .reports {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
    .card {{ background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); transition: box-shadow 0.2s; }}
    .card:hover {{ box-shadow: 0 4px 6px rgba(0,0,0,0.08); }}
    a {{ color: #0f172a; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .empty {{ text-align: center; color: #64748b; padding: 48px; }}
  </style>
</head>
<body>
  <h1>Radar Reports</h1>
  <div class="muted">Generated at {generated_at} (UTC)</div>

  {body_content}
</body>
</html>"""

    index_path = report_dir / "index.html"
    index_path.write_text(html_content, encoding="utf-8")
    return index_path
