"""
intelligence/views.py
=====================
Purpose:
    Revenue Intelligence views for administrators and staff.
    Guarded by role_required("admin", "staff") to prevent customer access.
"""

import json
from django.shortcuts import render
from accounts.decorators import role_required
from .services import get_mrr, get_revenue_trend


@role_required("admin", "staff")
def revenue_dashboard_view(request):
    """
    Main Revenue Intelligence Dashboard:
      - Monthly Recurring Revenue (MRR) & ARR
      - Monthly revenue trend (last 12 months)
      - Month-over-Month (MoM) growth %
      - Interactive Chart.js trend visualization
    """
    mrr_data = get_mrr()
    trend_data = get_revenue_trend(months=12)

    context = {
        "mrr_data": mrr_data,
        "trend_data": trend_data,
        "chart_labels_json": json.dumps(trend_data["labels"]),
        "chart_data_json": json.dumps(trend_data["data"]),
        "active_tab": "revenue",
    }

    return render(request, "intelligence/dashboard.html", context)


@role_required("admin", "staff")
def forecast_health_view(request):
    """
    Feature 2: Forecast, Health Score & Churn Risk:
      - 3-Month revenue forecast using linear trend + moving average
      - Subscription Health Scores (0 to 100)
      - Churn Risk Classification (High / Medium / Low)
      - High-performance paginated table sorted by highest risk
    """
    from django.core.paginator import Paginator
    from .services import forecast_revenue, get_subscription_health_scores

    status_filter = request.GET.get("status", "").strip() or None
    forecast_data = forecast_revenue(months_ahead=3)
    health_data = get_subscription_health_scores(status_filter=status_filter)

    # Paginate subscriptions (25 per page) for instant rendering with 3,000+ records
    paginator = Paginator(health_data["subscriptions"], 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "forecast_data": forecast_data,
        "health_stats": health_data,
        "page_obj": page_obj,
        "status_filter": status_filter or "",
        "chart_labels_json": json.dumps(forecast_data["combined_chart_labels"]),
        "chart_historical_json": json.dumps(forecast_data["historical_series"]),
        "chart_forecast_json": json.dumps(forecast_data["forecast_series"]),
        "active_tab": "forecast",
    }

    return render(request, "intelligence/forecast_health.html", context)

