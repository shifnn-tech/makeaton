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
