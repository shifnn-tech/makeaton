"""
intelligence/services.py
========================
Purpose:
    Core domain calculations for the BrightLoop Revenue Intelligence module.
    Encapsulates financial intelligence logic in plain, easily testable functions:
      - MRR & ARR calculation (with frequency normalization)
      - Monthly revenue trend & Month-over-Month (MoM) growth %
      - Graceful handling of empty datasets and zero divisions
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from subscriptions.models import Subscription
from catalog.models import Plan
from billing.models import Payment, Invoice


def quantize_currency(amount: Decimal) -> Decimal:
    """Helper to round any decimal to two decimal places."""
    if amount is None:
        return Decimal("0.00")
    return Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_to_monthly(price: Decimal, billing_period: str) -> Decimal:
    """
    Normalizes a subscription price to its Monthly Recurring Revenue (MRR) equivalent:
      - Daily:   price * 30
      - Weekly:  price * 4.33
      - Monthly: price * 1.0
      - Yearly:  price / 12.0
    """
    if not price or price <= Decimal("0.00"):
        return Decimal("0.00")

    period = (billing_period or "").lower().strip()
    if period == Plan.PERIOD_DAILY:
        monthly_val = price * Decimal("30")
    elif period == Plan.PERIOD_WEEKLY:
        monthly_val = price * Decimal("4.33")
    elif period == Plan.PERIOD_YEARLY:
        monthly_val = price / Decimal("12")
    else:  # Defaults to monthly
        monthly_val = price * Decimal("1")

    return quantize_currency(monthly_val)


def get_mrr() -> dict:
    """
    Calculates current Monthly Recurring Revenue (MRR) and Annual Recurring Revenue (ARR)
    across all Active subscriptions.

    Returns:
        dict: {
            'mrr': Decimal,
            'arr': Decimal,
            'active_count': int,
            'by_period': dict
        }
    """
    active_subs = (
        Subscription.objects.filter(status=Subscription.STATUS_ACTIVE)
        .select_related("plan")
        .only("id", "plan__price", "plan__billing_period")
    )

    total_mrr = Decimal("0.00")
    by_period = {
        Plan.PERIOD_DAILY: {"count": 0, "mrr": Decimal("0.00")},
        Plan.PERIOD_WEEKLY: {"count": 0, "mrr": Decimal("0.00")},
        Plan.PERIOD_MONTHLY: {"count": 0, "mrr": Decimal("0.00")},
        Plan.PERIOD_YEARLY: {"count": 0, "mrr": Decimal("0.00")},
    }

    active_count = 0
    for sub in active_subs:
        active_count += 1
        plan = sub.plan
        period = plan.billing_period if plan else Plan.PERIOD_MONTHLY
        price = plan.price if plan else Decimal("0.00")

        monthly_amount = normalize_to_monthly(price, period)
        total_mrr += monthly_amount

        if period in by_period:
            by_period[period]["count"] += 1
            by_period[period]["mrr"] += monthly_amount

    total_mrr = quantize_currency(total_mrr)
    total_arr = quantize_currency(total_mrr * Decimal("12"))

    return {
        "mrr": total_mrr,
        "arr": total_arr,
        "active_count": active_count,
        "by_period": by_period,
    }


def get_revenue_trend(months: int = 12) -> dict:
    """
    Calculates monthly settled revenue from Payments over the last N completed months,
    along with Month-over-Month (MoM) growth rates based on the last COMPLETE month.

    Excludes incomplete current month from the trend curve and growth % calculation
    so an artificial MoM drop is not shown.

    Returns:
        dict: {
            'trend': list of dicts [{'month_key': 'YYYY-MM', 'label': 'Mon YYYY', 'revenue': Decimal, 'growth_pct': float}],
            'labels': list of str (for Chart.js),
            'data': list of float (for Chart.js),
            'latest_revenue': Decimal,
            'latest_mom_growth': float,
            'latest_month_label': str,
            'total_period_revenue': Decimal,
            'partial_month_revenue': Decimal,
            'partial_month_label': str,
            'has_partial_month': bool,
        }
    """
    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    cutoff_date = (current_month_start - timedelta(days=(months * 31))).replace(day=1)

    # 1. Query strictly completed months (date < current_month_start)
    completed_payments = (
        Payment.objects.filter(
            date__gte=cutoff_date,
            date__lt=current_month_start,
            amount__gt=0,
        )
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total_revenue=Sum("amount"))
        .order_by("month")
    )

    # 2. Check for current month (MTD / incomplete) payments
    partial_payments = (
        Payment.objects.filter(date__gte=current_month_start, amount__gt=0)
        .aggregate(total_revenue=Sum("amount"))
    )
    partial_revenue = quantize_currency(partial_payments["total_revenue"] or Decimal("0.00"))

    trend = []
    labels = []
    data = []
    prev_revenue = None
    total_period_revenue = Decimal("0.00")

    # If there are completed months, use them
    target_entries = list(completed_payments)
    
    # Graceful fallback: if no completed months exist at all (e.g. fresh database created today),
    # query all payments so the view still shows data rather than an empty page.
    if not target_entries:
        fallback_payments = (
            Payment.objects.filter(amount__gt=0)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_revenue=Sum("amount"))
            .order_by("month")
        )
        target_entries = list(fallback_payments)

    for entry in target_entries:
        m_date: date = entry["month"]
        rev: Decimal = quantize_currency(entry["total_revenue"] or Decimal("0.00"))
        total_period_revenue += rev

        # Compute Month-over-Month % change
        growth_pct = None
        if prev_revenue is not None:
            if prev_revenue > Decimal("0.00"):
                growth = ((rev - prev_revenue) / prev_revenue) * Decimal("100")
                growth_pct = round(float(growth), 1)
            else:
                growth_pct = 100.0 if rev > Decimal("0.00") else 0.0

        label_str = m_date.strftime("%b %Y") if hasattr(m_date, "strftime") else str(m_date)[:7]
        month_key = m_date.strftime("%Y-%m") if hasattr(m_date, "strftime") else str(m_date)[:7]

        trend.append({
            "month_key": month_key,
            "label": label_str,
            "revenue": rev,
            "growth_pct": growth_pct,
        })
        labels.append(label_str)
        data.append(float(rev))
        prev_revenue = rev

    # Determine latest completed month revenue and growth
    latest_revenue = trend[-1]["revenue"] if trend else Decimal("0.00")
    latest_mom_growth = trend[-1]["growth_pct"] if trend and trend[-1]["growth_pct"] is not None else 0.0
    latest_month_label = trend[-1]["label"] if trend else "N/A"

    return {
        "trend": trend,
        "labels": labels,
        "data": data,
        "latest_revenue": latest_revenue,
        "latest_mom_growth": latest_mom_growth,
        "latest_month_label": latest_month_label,
        "total_period_revenue": quantize_currency(total_period_revenue),
        "partial_month_revenue": partial_revenue,
        "partial_month_label": today.strftime("%b %Y"),
        "has_partial_month": partial_revenue > Decimal("0.00"),
    }


def forecast_revenue(months_ahead: int = 3) -> dict:
    """
    Projects revenue for the next N months using a linear regression trend
    blended with a 3-month Simple Moving Average (SMA).

    Assumptions:
      - Uses completed monthly historical payments to avoid incomplete cycle bias.
      - Fits a linear slope (y = mx + c) and blends with recent moving average.
      - Projects next 3 calendar months with non-negative constraints.

    Returns:
        dict: {
            'forecast': list of dicts [{'label': 'Mon YYYY', 'month_key': 'YYYY-MM', 'projected_revenue': Decimal}],
            'total_projected': Decimal,
            'avg_monthly_projection': Decimal,
            'combined_chart_labels': list of str,
            'historical_series': list of (float or None),
            'forecast_series': list of (float or None),
            'assumptions': str,
        }
    """
    trend_data = get_revenue_trend(months=12)
    historical_entries = trend_data["trend"]
    y_vals = [float(x["revenue"]) for x in historical_entries]
    n = len(y_vals)

    forecast_items = []
    total_projected = Decimal("0.00")

    # Determine starting month for future projections
    if historical_entries:
        last_key = historical_entries[-1]["month_key"]  # e.g. "2026-09"
        y_int, m_int = int(last_key.split("-")[0]), int(last_key.split("-")[1])
    else:
        today = timezone.localdate()
        y_int, m_int = today.year, today.month

    if n >= 2:
        # Linear Regression: y = m*x + c
        x_vals = list(range(1, n + 1))
        mean_x = sum(x_vals) / n
        mean_y = sum(y_vals) / n

        num = sum((x_vals[i] - mean_x) * (y_vals[i] - mean_y) for i in range(n))
        den = sum((x_vals[i] - mean_x) ** 2 for i in range(n))
        slope = num / den if den != 0 else 0.0
        intercept = mean_y - slope * mean_x

        # 3-month moving average of most recent observations
        recent_window = y_vals[-3:] if n >= 3 else y_vals
        sma_recent = sum(recent_window) / len(recent_window)

        for step in range(1, months_ahead + 1):
            future_x = n + step
            linear_estimate = slope * future_x + intercept
            # 70% linear trend + 30% moving average smoothing
            blended = max(0.0, (0.7 * linear_estimate) + (0.3 * sma_recent))
            proj_decimal = quantize_currency(Decimal(str(round(blended, 2))))
            total_projected += proj_decimal

            # Advance calendar month
            m_target = m_int + step
            y_target = y_int + ((m_target - 1) // 12)
            m_normalized = ((m_target - 1) % 12) + 1
            step_date = date(y_target, m_normalized, 1)

            forecast_items.append({
                "label": step_date.strftime("%b %Y"),
                "month_key": step_date.strftime("%Y-%m"),
                "projected_revenue": proj_decimal,
                "step": step,
            })
    elif n == 1:
        # Fallback with 1 data point: flat projection
        single_val = quantize_currency(Decimal(str(y_vals[0])))
        for step in range(1, months_ahead + 1):
            m_target = m_int + step
            y_target = y_int + ((m_target - 1) // 12)
            m_normalized = ((m_target - 1) % 12) + 1
            step_date = date(y_target, m_normalized, 1)
            total_projected += single_val
            forecast_items.append({
                "label": step_date.strftime("%b %Y"),
                "month_key": step_date.strftime("%Y-%m"),
                "projected_revenue": single_val,
                "step": step,
            })
    else:
        # Fallback when 0 payments: use MRR as base
        mrr_fallback = get_mrr()["mrr"]
        for step in range(1, months_ahead + 1):
            m_target = m_int + step
            y_target = y_int + ((m_target - 1) // 12)
            m_normalized = ((m_target - 1) % 12) + 1
            step_date = date(y_target, m_normalized, 1)
            total_projected += mrr_fallback
            forecast_items.append({
                "label": step_date.strftime("%b %Y"),
                "month_key": step_date.strftime("%Y-%m"),
                "projected_revenue": mrr_fallback,
                "step": step,
            })

    avg_monthly = quantize_currency(total_projected / Decimal(str(months_ahead))) if months_ahead > 0 else Decimal("0.00")

    # Build connected Chart.js dataset:
    # Historical curve ends at last historical month;
    # Forecast curve connects from last historical month into projected months.
    combined_labels = [x["label"] for x in historical_entries] + [x["label"] for x in forecast_items]
    historical_series = [float(x["revenue"]) for x in historical_entries] + [None] * len(forecast_items)
    
    forecast_series = [None] * (len(historical_entries) - 1 if len(historical_entries) > 0 else 0)
    if historical_entries:
        forecast_series.append(float(historical_entries[-1]["revenue"]))  # Anchor to connect lines
    forecast_series.extend([float(x["projected_revenue"]) for x in forecast_items])

    return {
        "forecast": forecast_items,
        "total_projected": quantize_currency(total_projected),
        "avg_monthly_projection": avg_monthly,
        "combined_chart_labels": combined_labels,
        "historical_series": historical_series,
        "forecast_series": forecast_series,
        "assumptions": (
            "Assumptions: Projects the next 3 months using a blended linear regression trend (70% weight) "
            "and 3-month Simple Moving Average (30% weight) over completed historical billing cycles. "
            "Assumes current subscriber retention patterns remain stable."
        ),
    }


def get_subscription_health_scores(status_filter: str = None) -> dict:
    """
    Computes Health Score (0-100) and Churn Risk (High / Medium / Low) per subscription.

    Health Score Components (0-100 points):
      1. On-Time Payment Rate (0-50 pts): Ratio of invoices paid on time vs total invoices.
      2. Overdue Penalty (0-30 pts): 30 pts base minus 15 pts per active overdue invoice.
      3. Subscriber Tenure / Age (0-20 pts): 2 pts per active month up to 20 pts (10+ months).

    Churn Risk Rules:
      - High Risk:   Score < 50, OR >= 2 overdue invoices, OR status is Closed.
      - Medium Risk: Score 50 to 74, OR exactly 1 overdue invoice.
      - Low Risk:    Score >= 75 AND 0 overdue invoices.

    Optimized with database aggregation (Count, Q) in a single query.
    Returns subscriptions sorted by HIGHEST RISK first.
    """
    from django.db.models import Count, Q

    today = timezone.localdate()

    qs = Subscription.objects.select_related("customer", "plan")
    if status_filter:
        qs = qs.filter(status=status_filter)

    # Database-level aggregate subqueries: eliminates N+1 loops!
    annotated_subs = qs.annotate(
        total_invoices_count=Count("invoices", distinct=True),
        paid_invoices_count=Count(
            "invoices",
            filter=Q(invoices__status=Invoice.STATUS_PAID),
            distinct=True,
        ),
        overdue_invoices_count=Count(
            "invoices",
            filter=Q(invoices__due_date__lt=today) & ~Q(invoices__status=Invoice.STATUS_PAID),
            distinct=True,
        ),
    )

    scored_list = []
    high_count = 0
    medium_count = 0
    low_count = 0
    total_score_sum = 0

    for sub in annotated_subs:
        total_inv = sub.total_invoices_count
        paid_inv = sub.paid_invoices_count
        overdue_inv = sub.overdue_invoices_count

        # 1. On-time payment ratio (0 - 50 points)
        if total_inv > 0:
            on_time_ratio = paid_inv / total_inv
            score_on_time = on_time_ratio * 50.0
        else:
            # New subscriber with no invoices yet: neutral baseline of 40/50
            on_time_ratio = 1.0
            score_on_time = 40.0

        # 2. Overdue penalty (0 - 30 points)
        score_overdue = max(0.0, 30.0 - (overdue_inv * 15.0))

        # 3. Tenure age (0 - 20 points)
        start_d = sub.start_date or today
        age_days = max(0, (today - start_d).days)
        age_months = max(1, age_days // 30)
        score_age = min(20.0, age_months * 2.0)

        # Total combined score clamped between 0 and 100
        raw_score = score_on_time + score_overdue + score_age
        health_score = int(round(min(100.0, max(0.0, raw_score))))
        total_score_sum += health_score

        # Churn Risk Label Assignment
        is_closed = (sub.status == Subscription.STATUS_CLOSED)
        if is_closed or health_score < 50 or overdue_inv >= 2:
            risk_label = "High"
            risk_badge_class = "risk-badge-high"
            risk_rank = 1  # Top priority for action
            high_count += 1
            risk_reason = "Multiple overdue invoices or critical health score (<50)" if not is_closed else "Subscription closed/cancelled"
        elif health_score < 75 or overdue_inv == 1:
            risk_label = "Medium"
            risk_badge_class = "risk-badge-medium"
            risk_rank = 2
            medium_count += 1
            risk_reason = "1 overdue invoice or moderate payment delays"
        else:
            risk_label = "Low"
            risk_badge_class = "risk-badge-low"
            risk_rank = 3
            low_count += 1
            risk_reason = "Consistent on-time payments and good contract tenure"

        scored_list.append({
            "id": sub.id,
            "number": sub.number,
            "customer_email": sub.customer.email,
            "customer_name": sub.customer.get_full_name() or sub.customer.email,
            "plan_name": sub.plan.name if sub.plan else "N/A",
            "plan_price": sub.plan.price if sub.plan else Decimal("0.00"),
            "status": sub.status,
            "start_date": sub.start_date,
            "age_months": age_months,
            "total_invoices": total_inv,
            "paid_invoices": paid_inv,
            "overdue_invoices": overdue_inv,
            "health_score": health_score,
            "risk_label": risk_label,
            "risk_badge_class": risk_badge_class,
            "risk_rank": risk_rank,
            "risk_reason": risk_reason,
        })

    # Sort strictly by HIGHEST RISK first (rank 1 -> 2 -> 3), then lowest health score
    scored_list.sort(key=lambda s: (s["risk_rank"], s["health_score"]))

    total_subs = len(scored_list)
    avg_score = round(total_score_sum / total_subs, 1) if total_subs > 0 else 0.0

    return {
        "subscriptions": scored_list,
        "total_count": total_subs,
        "high_risk_count": high_count,
        "medium_risk_count": medium_count,
        "low_risk_count": low_count,
        "avg_health_score": avg_score,
        "assumptions": (
            "Health score (0-100) combines: On-Time Payment Rate (up to 50 pts), "
            "Overdue Penalty (-15 pts per unpaid bill, up to 30 pts), and Tenure Age "
            "(2 pts per active month up to 20 pts). Churn risk is flagged as High if score < 50 "
            "or 2+ invoices are past due."
        ),
    }
