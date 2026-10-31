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
