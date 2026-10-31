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


@role_required("admin", "staff")
def leak_detector_view(request):
    """
    Feature 3: Revenue Leak Detector:
      - Total revenue at risk summary card
      - Five independent leak audits:
          1. Active subscriptions with no invoice for current period
          2. Failed or lapsed renewals
          3. Unpaid invoices past their due date
          4. Payments not matched or exceeding invoice
          5. Invoices whose total does not equal sum of lines
    """
    from .services import detect_leaks
    leak_data = detect_leaks()

    context = {
        "leak_data": leak_data,
        "active_tab": "leaks",
    }
    return render(request, "intelligence/leaks.html", context)


@role_required("admin", "staff")
def simulator_view(request):
    """
    Feature 4: What-If Revenue Simulator:
      - 3 interactive sliders: Price Increase %, Customer Growth %, Churn %
      - 12-month projected MRR & ARR
      - Live browser recalculation without reload
      - Formula transparency & simulation disclaimer
    """
    from .services import simulate, get_mrr

    mrr_info = get_mrr()
    base_mrr = mrr_info["mrr"]

    # Initial default simulation (0% price change, 5% growth, 3% churn)
    sim_data = simulate(
        base_mrr=base_mrr,
        price_increase_pct=0.0,
        customer_growth_pct=5.0,
        churn_pct=3.0,
        months=12,
    )

    context = {
        "base_mrr": base_mrr,
        "active_subscribers_count": mrr_info.get("active_count", 0),
        "sim_data": sim_data,
        "chart_labels_json": json.dumps(sim_data["labels"]),
        "chart_simulated_json": json.dumps(sim_data["simulated_series"]),
        "chart_baseline_json": json.dumps(sim_data["baseline_series"]),
        "active_tab": "simulator",
    }
    return render(request, "intelligence/simulator.html", context)

