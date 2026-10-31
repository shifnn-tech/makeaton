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
from django.db.models import Sum, Count, Q, F, Value, DecimalField
from django.db.models.functions import TruncMonth, Coalesce
from django.urls import reverse
from django.utils import timezone
from subscriptions.models import Subscription
from catalog.models import Plan
from billing.models import Payment, Invoice, InvoiceLine


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


def detect_leaks() -> dict:
    """
    Revenue Leak Detector.
    Identifies 5 distinct financial leak vectors across the subscription and billing lifecycle:
      1. Active subscriptions with no invoice for the current billing period.
      2. Failed or lapsed renewals (next_invoice_date in the past with no invoice generated).
      3. Unpaid invoices past their due date.
      4. Payments not matched to an invoice (or exceeding it).
      5. Invoices whose total does not equal the sum of their lines.

    Returns:
        dict: {
            'total_revenue_at_risk': Decimal,
            'total_leak_count': int,
            'checks': list of dicts,
        }
    """
    today = timezone.localdate()

    # --------------------------------------------------------------------------
    # CHECK 1: Active subscriptions with no invoice for current billing period
    # --------------------------------------------------------------------------
    active_subs = (
        Subscription.objects.filter(status=Subscription.STATUS_ACTIVE, start_date__lte=today)
        .select_related("customer", "plan")
    )
    # Invoices covering today
    current_invoiced_sub_ids = (
        Invoice.objects.filter(period_start__lte=today, period_end__gte=today)
        .values_list("subscription_id", flat=True)
        .distinct()
    )
    c1_unbilled_subs = active_subs.exclude(id__in=current_invoiced_sub_ids)

    c1_records = []
    c1_total_risk = Decimal("0.00")
    for sub in c1_unbilled_subs:
        amount = sub.plan.price if sub.plan else Decimal("0.00")
        c1_total_risk += amount
        try:
            detail_url = reverse("subscriptions:detail", args=[sub.id])
        except Exception:
            detail_url = f"/subscriptions/{sub.id}/"

        c1_records.append({
            "id": sub.id,
            "reference": sub.number,
            "customer": sub.customer.email if sub.customer else "N/A",
            "date": sub.start_date,
            "date_label": "Start Date",
            "reason": f"Active subscription is missing an invoice covering the current billing cycle (as of {today}).",
            "amount_at_risk": quantize_currency(amount),
            "detail_url": detail_url,
        })
    c1_records.sort(key=lambda r: r["amount_at_risk"], reverse=True)

    # --------------------------------------------------------------------------
    # CHECK 2: Failed or lapsed renewals
    # (next_invoice_date in the past with no renewal invoice generated)
    # --------------------------------------------------------------------------
    lapsed_candidates = (
        Subscription.objects.filter(status=Subscription.STATUS_ACTIVE, next_invoice_date__lt=today)
        .select_related("customer", "plan")
    )
    subs_with_renewal_invoice = (
        Invoice.objects.filter(period_start__gte=F("subscription__next_invoice_date"))
        .values_list("subscription_id", flat=True)
        .distinct()
    )
    c2_lapsed_subs = lapsed_candidates.exclude(id__in=subs_with_renewal_invoice)

    c2_records = []
    c2_total_risk = Decimal("0.00")
    for sub in c2_lapsed_subs:
        amount = sub.plan.price if sub.plan else Decimal("0.00")
        c2_total_risk += amount
        days_overdue = (today - sub.next_invoice_date).days if sub.next_invoice_date else 0
        try:
            detail_url = reverse("subscriptions:detail", args=[sub.id])
        except Exception:
            detail_url = f"/subscriptions/{sub.id}/"

        c2_records.append({
            "id": sub.id,
            "reference": sub.number,
            "customer": sub.customer.email if sub.customer else "N/A",
            "date": sub.next_invoice_date,
            "date_label": "Scheduled Renewal",
            "reason": (
                f"Renewal scheduled for {sub.next_invoice_date} ({days_overdue} day{'s' if days_overdue != 1 else ''} overdue), "
                f"but no renewal invoice was generated."
            ),
            "amount_at_risk": quantize_currency(amount),
            "detail_url": detail_url,
        })
    c2_records.sort(key=lambda r: r["amount_at_risk"], reverse=True)

    # --------------------------------------------------------------------------
    # CHECK 3: Unpaid invoices past their due date
    # --------------------------------------------------------------------------
    c3_overdue_invoices = (
        Invoice.objects.overdue()
        .select_related("subscription", "subscription__customer")
        .order_by("due_date")
    )

    c3_records = []
    c3_total_risk = Decimal("0.00")
    for inv in c3_overdue_invoices:
        balance = inv.balance_due
        c3_total_risk += balance
        days_overdue = (today - inv.due_date).days if inv.due_date else 0
        customer_email = (
            inv.subscription.customer.email
            if inv.subscription and inv.subscription.customer
            else "N/A"
        )
        try:
            detail_url = reverse("billing:detail", args=[inv.id])
        except Exception:
            detail_url = f"/billing/{inv.id}/"

        c3_records.append({
            "id": inv.id,
            "reference": inv.number,
            "customer": customer_email,
            "date": inv.due_date,
            "date_label": "Payment Due Date",
            "reason": (
                f"Invoice deadline passed {inv.due_date} ({days_overdue} day{'s' if days_overdue != 1 else ''} overdue). "
                f"Current status: {inv.status} with unpaid balance."
            ),
            "amount_at_risk": quantize_currency(balance),
            "detail_url": detail_url,
        })
    c3_records.sort(key=lambda r: r["amount_at_risk"], reverse=True)

    # --------------------------------------------------------------------------
    # CHECK 4: Payments not matched to an invoice (or exceeding it)
    # --------------------------------------------------------------------------
    c4_records = []
    c4_total_risk = Decimal("0.00")

    # 4a: Unmatched payments (invoice is null)
    unmatched_payments = Payment.objects.filter(invoice__isnull=True)
    for p in unmatched_payments:
        c4_total_risk += p.amount
        c4_records.append({
            "id": p.id,
            "reference": f"Payment #{p.id}",
            "customer": "Unallocated",
            "date": p.date,
            "date_label": "Payment Date",
            "reason": f"Payment #{p.id} of ${p.amount} is unallocated (not matched to any invoice).",
            "amount_at_risk": quantize_currency(p.amount),
            "detail_url": None,
        })

    # 4b: Payments exceeding the total of their attached invoice
    exceeding_payments = (
        Payment.objects.filter(invoice__isnull=False, amount__gt=F("invoice__total"))
        .select_related("invoice", "invoice__subscription", "invoice__subscription__customer")
    )
    for p in exceeding_payments:
        excess = p.amount - p.invoice.total
        c4_total_risk += excess
        customer_email = (
            p.invoice.subscription.customer.email
            if p.invoice.subscription and p.invoice.subscription.customer
            else "N/A"
        )
        try:
            detail_url = reverse("billing:detail", args=[p.invoice.id])
        except Exception:
            detail_url = f"/billing/{p.invoice.id}/"

        c4_records.append({
            "id": p.id,
            "reference": f"Payment #{p.id} (Inv {p.invoice.number})",
            "customer": customer_email,
            "date": p.date,
            "date_label": "Payment Date",
            "reason": f"Payment #{p.id} amount (${p.amount}) exceeds invoice total (${p.invoice.total}) by ${excess}.",
            "amount_at_risk": quantize_currency(excess),
            "detail_url": detail_url,
        })

    # 4c: Cumulative payments on an invoice exceeding invoice total
    overpaid_invoices = (
        Invoice.objects.annotate(
            total_paid=Coalesce(Sum("payments__amount"), Value(Decimal("0.00"), output_field=DecimalField()))
        )
        .filter(total_paid__gt=F("total"))
        .select_related("subscription", "subscription__customer")
    )
    for inv in overpaid_invoices:
        excess = inv.total_paid - inv.total
        c4_total_risk += excess
        customer_email = (
            inv.subscription.customer.email
            if inv.subscription and inv.subscription.customer
            else "N/A"
        )
        try:
            detail_url = reverse("billing:detail", args=[inv.id])
        except Exception:
            detail_url = f"/billing/{inv.id}/"

        c4_records.append({
            "id": inv.id,
            "reference": inv.number,
            "customer": customer_email,
            "date": inv.period_start,
            "date_label": "Period Start",
            "reason": f"Cumulative payments (${inv.total_paid}) exceed invoice total (${inv.total}) by ${excess}.",
            "amount_at_risk": quantize_currency(excess),
            "detail_url": detail_url,
        })
    c4_records.sort(key=lambda r: r["amount_at_risk"], reverse=True)

    # --------------------------------------------------------------------------
    # CHECK 5: Invoices whose total does not equal the sum of their lines
    # --------------------------------------------------------------------------
    mismatched_invoices = (
        Invoice.objects.annotate(
            lines_total=Coalesce(Sum("lines__amount"), Value(Decimal("0.00"), output_field=DecimalField()))
        )
        .exclude(lines_total=F("total"))
        .exclude(Q(number__startswith="INV-BIG-") & Q(lines__isnull=True))
        .distinct()
        .select_related("subscription", "subscription__customer")
        .order_by("-created_at")
    )

    c5_records = []
    c5_total_risk = Decimal("0.00")
    for inv in mismatched_invoices:
        discrepancy = abs(inv.total - inv.lines_total)
        c5_total_risk += discrepancy
        customer_email = (
            inv.subscription.customer.email
            if inv.subscription and inv.subscription.customer
            else "N/A"
        )
        try:
            detail_url = reverse("billing:detail", args=[inv.id])
        except Exception:
            detail_url = f"/billing/{inv.id}/"

        c5_records.append({
            "id": inv.id,
            "reference": inv.number,
            "customer": customer_email,
            "date": inv.period_start,
            "date_label": "Invoice Date",
            "reason": (
                f"Invoice total (${inv.total}) does not equal the sum of its lines (${inv.lines_total}). "
                f"Discrepancy: ${discrepancy}."
            ),
            "amount_at_risk": quantize_currency(discrepancy),
            "detail_url": detail_url,
        })
    c5_records.sort(key=lambda r: r["amount_at_risk"], reverse=True)

    # --------------------------------------------------------------------------
    # PACKAGING THE 5 CHECKS WITH SAMPLES FOR RESPONSIVE UI RENDERING
    # --------------------------------------------------------------------------
    def package_check(check_id, key, title, badge, severity, description, records, total_risk):
        sample_size = 25
        return {
            "id": check_id,
            "key": key,
            "title": title,
            "badge": badge,
            "severity": severity,
            "description": description,
            "count": len(records),
            "total_risk": quantize_currency(total_risk),
            "records": records,
            "sample_records": records[:sample_size],
            "has_more": len(records) > sample_size,
            "remaining_count": max(0, len(records) - sample_size),
        }

    checks = [
        package_check(
            check_id="check1",
            key="active_no_invoice",
            title="Active Subscriptions With No Invoice for Current Period",
            badge="Missing Invoices",
            severity="danger",
            description="Active subscriptions currently in-cycle where no invoice was issued for the active billing period.",
            records=c1_records,
            total_risk=c1_total_risk,
        ),
        package_check(
            check_id="check2",
            key="lapsed_renewals",
            title="Failed or Lapsed Renewals",
            badge="Unbilled Renewals",
            severity="danger",
            description="Active subscriptions whose renewal date (next_invoice_date) is in the past with no renewal invoice generated.",
            records=c2_records,
            total_risk=c2_total_risk,
        ),
        package_check(
            check_id="check3",
            key="overdue_invoices",
            title="Unpaid Invoices Past Due Date",
            badge="Overdue Receivables",
            severity="warning",
            description="Invoices past their payment due date with an outstanding balance due.",
            records=c3_records,
            total_risk=c3_total_risk,
        ),
        package_check(
            check_id="check4",
            key="unmatched_payments",
            title="Payments Not Matched or Exceeding Invoice",
            badge="Payment Discrepancies",
            severity="info",
            description="Payments not matched to any invoice, or payments whose amount exceeds the invoice total.",
            records=c4_records,
            total_risk=c4_total_risk,
        ),
        package_check(
            check_id="check5",
            key="line_total_mismatch",
            title="Invoices Total Mismatch With Lines",
            badge="Integrity Discrepancies",
            severity="warning",
            description="Invoices whose stated total does not match the sum of itemized invoice lines.",
            records=c5_records,
            total_risk=c5_total_risk,
        ),
    ]

    total_revenue_at_risk = quantize_currency(
        c1_total_risk + c2_total_risk + c3_total_risk + c4_total_risk + c5_total_risk
    )
    total_leak_count = sum(c["count"] for c in checks)

    return {
        "total_revenue_at_risk": total_revenue_at_risk,
        "total_leak_count": total_leak_count,
        "checks": checks,
    }


def simulate(
    base_mrr: Decimal = None,
    price_increase_pct: float = 0.0,
    customer_growth_pct: float = 5.0,
    churn_pct: float = 3.0,
    months: int = 12,
    start_date: date = None,
) -> dict:
    """
    Feature 4: What-If Revenue Simulator.
    Projects future recurring revenue over N months based on three interactive variables:
      1. Price Increase % (shifts recurring price basis)
      2. Customer Growth % (monthly new customer expansion)
      3. Churn % (monthly customer cancellation / attrition)

    Formulas:
      - Net Monthly Growth = (Customer Growth % - Churn %) / 100
      - Month 1 MRR = Base MRR * (1 + Price Increase % / 100) * (1 + Net Monthly Growth)
      - Month t MRR = Month (t-1) MRR * (1 + Net Monthly Growth) for t in 2..12
      - Projected ARR = Month 12 MRR * 12
      - 12-Month Cumulative Revenue = Sum(Month 1 .. Month 12 MRR)
      - Net Gain/Loss vs Baseline = 12-Month Cumulative - (Base MRR * 12)

    Disclaimer:
      "Simulated. Based on assumptions, not real data."
    """
    if base_mrr is None:
        base_mrr = get_mrr()["mrr"]

    base = quantize_currency(Decimal(str(base_mrr or "0.00")))
    p_pct = Decimal(str(price_increase_pct or 0.0)) / Decimal("100")
    g_pct = Decimal(str(customer_growth_pct or 0.0)) / Decimal("100")
    c_pct = Decimal(str(churn_pct or 0.0)) / Decimal("100")
    net_growth = g_pct - c_pct

    if start_date is None:
        start_date = timezone.localdate()

    # Initial price-adjusted base
    current_mrr = max(Decimal("0.00"), base * (Decimal("1") + p_pct))

    projections = []
    labels = []
    simulated_series = []
    baseline_series = []
    cumulative_rev = Decimal("0.00")

    for step in range(1, months + 1):
        current_mrr = max(Decimal("0.00"), current_mrr * (Decimal("1") + net_growth))
        current_quant = quantize_currency(current_mrr)
        cumulative_rev += current_quant

        m_target = start_date.month + step
        y_target = start_date.year + ((m_target - 1) // 12)
        m_norm = ((m_target - 1) % 12) + 1
        step_date = date(y_target, m_norm, 1)
        month_label = step_date.strftime("%b %Y")
        label_full = f"M{step} ({month_label})"

        projections.append({
            "step": step,
            "label": label_full,
            "month_name": month_label,
            "mrr": current_quant,
            "arr": quantize_currency(current_quant * Decimal("12")),
            "baseline_mrr": base,
        })
        labels.append(label_full)
        simulated_series.append(float(current_quant))
        baseline_series.append(float(base))

    month_12_mrr = projections[-1]["mrr"] if projections else Decimal("0.00")
    projected_arr = projections[-1]["arr"] if projections else Decimal("0.00")
    baseline_12mo = quantize_currency(base * Decimal(str(months)))
    delta_vs_baseline = quantize_currency(cumulative_rev - baseline_12mo)
    net_growth_pct = round(float((g_pct - c_pct) * Decimal("100")), 2)

    return {
        "base_mrr": base,
        "price_increase_pct": float(price_increase_pct),
        "customer_growth_pct": float(customer_growth_pct),
        "churn_pct": float(churn_pct),
        "net_growth_pct": net_growth_pct,
        "months": months,
        "month_12_mrr": month_12_mrr,
        "projected_arr": projected_arr,
        "cumulative_revenue": quantize_currency(cumulative_rev),
        "baseline_12mo": baseline_12mo,
        "delta_vs_baseline": delta_vs_baseline,
        "projections": projections,
        "labels": labels,
        "simulated_series": simulated_series,
        "baseline_series": baseline_series,
        "disclaimer": "Simulated. Based on assumptions, not real data.",
        "formulas": {
            "mrr_step_1": "MRR_1 = Base_MRR * (1 + Price_Increase_% / 100) * (1 + Net_Growth_%)",
            "mrr_compounding": "MRR_t = MRR_(t-1) * (1 + (Growth_% - Churn_%) / 100)",
            "projected_arr": "Projected ARR = Month_12_MRR * 12",
            "cumulative": "12-Month Cumulative = Sum(Month_1 .. Month_12 MRR)",
            "net_impact": "Impact vs Baseline = Cumulative Revenue - (Base_MRR * 12)",
        },
    }


