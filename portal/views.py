"""
portal/views.py
===============
Views for the BrightLoop unified portal:
  1. landing_view: Checks the logged-in user's role and redirects to the right dashboard.
  2. admin_dashboard_view: Executive KPI counts, totals, and navigation to analytics.
  3. staff_dashboard_view: Operational queue of recent subscriptions, upcoming invoices, and overdue bills.
  4. customer_dashboard_view: Self-service portal showing only the logged-in customer's data.
  5. search_view: Global search across customer emails, subscription numbers, and invoice numbers.
  6. billing_calendar_view: Subscriptions renewing within the next 30 days, grouped by week.
  7. customer_list_view: Staff-only paginated table of customers with account health metrics.
  8. customer_detail_view: Staff-only full profile of a customer with their subscriptions, invoices, and payments.
"""

import datetime
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.utils import timezone

from accounts.models import User
from accounts.decorators import role_required
from subscriptions.models import Subscription
from billing.models import Invoice, Payment
from catalog.models import Plan


# ==============================================================================
# 1. ROLE-BASED LANDING VIEW
# ==============================================================================
@login_required
def landing_view(request):
    """
    Directs the user to their appropriate dashboard after logging in.
    - Superusers and Admins go to the Admin Dashboard.
    - Staff members go to the Staff Operations Dashboard.
    - Customers go to their personalized Customer Dashboard.
    """
    if request.user.is_superuser or request.user.role == User.ROLE_ADMIN:
        return redirect("portal:admin_dashboard")
    elif request.user.role == User.ROLE_STAFF:
        return redirect("portal:staff_dashboard")
    elif request.user.role == User.ROLE_CUSTOMER:
        return redirect("portal:customer_dashboard")
    return redirect("accounts:home")


# ==============================================================================
# 2. ADMIN DASHBOARD
# ==============================================================================
@role_required(User.ROLE_ADMIN)
def admin_dashboard_view(request):
    """
    Admin Executive Dashboard.
    Uses database-level Count() and Sum() aggregation to compute platform-wide KPIs:
      - Total registered users (broken down into customers and staff)
      - Count of active recurring subscriptions
      - Count and dollar total of unpaid invoices
      - Total revenue collected from all settled payments
    Also provides direct navigation cards to Finance Analytics and Intelligence.
    """
    # 1. User metrics
    total_users = User.objects.count()
    customer_count = User.objects.filter(role=User.ROLE_CUSTOMER).count()
    staff_count = User.objects.filter(role=User.ROLE_STAFF).count()

    # 2. Subscription metrics
    active_subscriptions_count = Subscription.objects.filter(
        status=Subscription.STATUS_ACTIVE
    ).count()
    total_subscriptions_count = Subscription.objects.count()

    # 3. Unpaid invoices aggregation (uses database Sum & Count, not Python loops)
    unpaid_invoice_stats = Invoice.objects.exclude(status=Invoice.STATUS_PAID).aggregate(
        count=Count("id"),
        total=Sum("total"),
    )
    unpaid_invoices_count = unpaid_invoice_stats["count"] or 0
    unpaid_invoices_total = unpaid_invoice_stats["total"] or Decimal("0.00")

    # 4. Total revenue collected from all recorded payments
    revenue_stats = Payment.objects.aggregate(total=Sum("amount"))
    total_revenue_received = revenue_stats["total"] or Decimal("0.00")

    # 5. Overdue invoices count
    overdue_count = Invoice.objects.overdue().count()

    # 6. Recent system activity (select_related eliminates N+1 SQL queries)
    recent_subscriptions = (
        Subscription.objects
        .select_related("customer", "plan")
        .order_by("-created_at")[:5]
    )
    recent_invoices = (
        Invoice.objects
        .select_related("subscription__customer", "subscription__plan")
        .order_by("-created_at")[:5]
    )

    context = {
        "total_users": total_users,
        "customer_count": customer_count,
        "staff_count": staff_count,
        "active_subscriptions_count": active_subscriptions_count,
        "total_subscriptions_count": total_subscriptions_count,
        "unpaid_invoices_count": unpaid_invoices_count,
        "unpaid_invoices_total": unpaid_invoices_total,
        "total_revenue_received": total_revenue_received,
        "overdue_count": overdue_count,
        "recent_subscriptions": recent_subscriptions,
        "recent_invoices": recent_invoices,
    }
    return render(request, "portal/admin_dashboard.html", context)


# ==============================================================================
# 3. STAFF DASHBOARD
# ==============================================================================
@role_required(User.ROLE_ADMIN, User.ROLE_STAFF)
def staff_dashboard_view(request):
    """
    Staff Operations Desk.
    Provides frontline customer-support staff with their primary task queues:
      - Recent subscriptions requiring review or activation
      - Invoices due soon (due within the next 14 days and still unpaid)
      - Overdue invoices requiring follow-up collections
    All queries use select_related to keep database hits minimal and fast.
    """
    today = timezone.localdate()
    due_soon_cutoff = today + datetime.timedelta(days=14)

    # 1. Recent subscriptions (ordered newest first)
    recent_subscriptions = (
        Subscription.objects
        .select_related("customer", "plan")
        .order_by("-created_at")[:8]
    )

    # 2. Invoices due soon (between today and +14 days, unpaid)
    invoices_due_soon = (
        Invoice.objects
        .select_related("subscription__customer", "subscription__plan")
        .filter(due_date__gte=today, due_date__lte=due_soon_cutoff)
        .exclude(status=Invoice.STATUS_PAID)
        .order_by("due_date")[:8]
    )

    # 3. Overdue invoices (due_date past today and not marked Paid)
    overdue_invoices = (
        Invoice.objects
        .select_related("subscription__customer", "subscription__plan")
        .overdue()
        .order_by("due_date")[:8]
    )

    # Aggregate metric counters for staff overview cards
    active_subs_count = Subscription.objects.filter(status=Subscription.STATUS_ACTIVE).count()
    due_soon_count = Invoice.objects.filter(
        due_date__gte=today,
        due_date__lte=due_soon_cutoff
    ).exclude(status=Invoice.STATUS_PAID).count()
    overdue_count = Invoice.objects.overdue().count()

    context = {
        "recent_subscriptions": recent_subscriptions,
        "invoices_due_soon": invoices_due_soon,
        "overdue_invoices": overdue_invoices,
        "active_subs_count": active_subs_count,
        "due_soon_count": due_soon_count,
        "overdue_count": overdue_count,
        "due_soon_days": 14,
    }
    return render(request, "portal/staff_dashboard.html", context)


# ==============================================================================
# 4. CUSTOMER DASHBOARD
# ==============================================================================
@role_required(User.ROLE_CUSTOMER)
def customer_dashboard_view(request):
    """
    Customer Self-Service Portal.
    Strictly restricted to only display the logged-in customer's own records:
      - Active subscriptions
      - Next upcoming billing/renewal date
      - Unpaid invoices and total balance due
    """
    customer = request.user
    today = timezone.localdate()

    # 1. Customer's active subscriptions (select_related plan for details)
    active_subscriptions = (
        Subscription.objects
        .select_related("plan")
        .filter(customer=customer, status=Subscription.STATUS_ACTIVE)
        .order_by("-start_date")
    )

    # 2. Next upcoming billing date from active contracts
    next_billing_date = (
        active_subscriptions
        .filter(next_invoice_date__gte=today)
        .order_by("next_invoice_date")
        .values_list("next_invoice_date", flat=True)
        .first()
    )

    # 3. Unpaid invoices for this customer
    unpaid_invoices = (
        Invoice.objects
        .select_related("subscription__plan")
        .filter(subscription__customer=customer)
        .exclude(status=Invoice.STATUS_PAID)
        .order_by("due_date")
    )

    # Aggregate total outstanding balance for customer
    unpaid_total = unpaid_invoices.aggregate(total=Sum("total"))["total"] or Decimal("0.00")

    # Additional summary counters
    total_subscriptions_count = Subscription.objects.filter(customer=customer).count()
    paid_invoices_count = Invoice.objects.filter(
        subscription__customer=customer,
        status=Invoice.STATUS_PAID
    ).count()

    context = {
        "active_subscriptions": active_subscriptions,
        "next_billing_date": next_billing_date,
        "unpaid_invoices": unpaid_invoices,
        "unpaid_total": unpaid_total,
        "total_subscriptions_count": total_subscriptions_count,
        "paid_invoices_count": paid_invoices_count,
    }
    return render(request, "portal/customer_dashboard.html", context)


# ==============================================================================
# 5. GLOBAL SEARCH
# ==============================================================================
@login_required
def search_view(request):
    """
    Cross-model global search using Django Q objects and icontains.
    Searches:
      - Customer accounts (by email, first name, last name)
      - Subscriptions (by subscription number, plan name, or customer email)
      - Invoices (by invoice number, subscription number, or customer email)
    Role security enforcement:
      - Staff and Admin can search all customers, subscriptions, and invoices.
      - Customers can ONLY search and see their own subscriptions and invoices.
    """
    query = request.GET.get("q", "").strip()
    is_internal_staff = request.user.is_superuser or request.user.role in [User.ROLE_ADMIN, User.ROLE_STAFF]

    customers = []
    subscriptions = []
    invoices = []

    if query:
        # 1. Customer user search (Internal staff and admin only)
        if is_internal_staff:
            customers = (
                User.objects
                .filter(role=User.ROLE_CUSTOMER)
                .filter(
                    Q(email__icontains=query) |
                    Q(first_name__icontains=query) |
                    Q(last_name__icontains=query)
                )
                .annotate(active_subs_count=Count("subscriptions", filter=Q(subscriptions__status=Subscription.STATUS_ACTIVE), distinct=True))[:10]
            )

        # 2. Subscription search (Scoped by role)
        sub_qs = Subscription.objects.select_related("customer", "plan")
        if not is_internal_staff:
            sub_qs = sub_qs.filter(customer=request.user)

        subscriptions = (
            sub_qs
            .filter(
                Q(number__icontains=query) |
                Q(plan__name__icontains=query) |
                Q(customer__email__icontains=query)
            )
            .order_by("-created_at")[:10]
        )

        # 3. Invoice search (Scoped by role)
        inv_qs = Invoice.objects.select_related("subscription__customer", "subscription__plan")
        if not is_internal_staff:
            inv_qs = inv_qs.filter(subscription__customer=request.user)

        invoices = (
            inv_qs
            .filter(
                Q(number__icontains=query) |
                Q(subscription__number__icontains=query) |
                Q(subscription__customer__email__icontains=query)
            )
            .order_by("-created_at")[:10]
        )

    total_results = len(customers) + len(subscriptions) + len(invoices)

    context = {
        "query": query,
        "customers": customers,
        "subscriptions": subscriptions,
        "invoices": invoices,
        "total_results": total_results,
        "is_internal_staff": is_internal_staff,
    }
    return render(request, "portal/search_results.html", context)


# ==============================================================================
# 6. BILLING CALENDAR & UPCOMING RENEWALS
# ==============================================================================
@login_required
def billing_calendar_view(request):
    """
    30-Day Billing Calendar.
    Finds active subscriptions whose next_invoice_date falls in the next 30 days.
    Groups them into 4 weekly buckets:
      - Week 1: Days 1 to 7
      - Week 2: Days 8 to 14
      - Week 3: Days 15 to 21
      - Week 4: Days 22 to 30
    Database aggregation calculates total renewal revenue per week without Python loops.
    """
    today = timezone.localdate()
    end_date = today + datetime.timedelta(days=30)
    is_internal_staff = request.user.is_superuser or request.user.role in [User.ROLE_ADMIN, User.ROLE_STAFF]

    # Base queryset for active subscriptions renewing in the next 30 days
    base_qs = (
        Subscription.objects
        .select_related("customer", "plan")
        .filter(
            status=Subscription.STATUS_ACTIVE,
            next_invoice_date__gte=today,
            next_invoice_date__lte=end_date,
        )
    )

    # Customers only see their own renewal dates
    if not is_internal_staff:
        base_qs = base_qs.filter(customer=request.user)

    # Define 4 weekly intervals
    intervals = [
        ("Week 1 (Next 7 Days)", today, today + datetime.timedelta(days=6)),
        ("Week 2 (Days 8 to 14)", today + datetime.timedelta(days=7), today + datetime.timedelta(days=13)),
        ("Week 3 (Days 15 to 21)", today + datetime.timedelta(days=14), today + datetime.timedelta(days=20)),
        ("Week 4 (Days 22 to 30)", today + datetime.timedelta(days=21), end_date),
    ]

    weeks = []
    grand_total_subs = 0
    grand_total_amount = Decimal("0.00")

    for title, w_start, w_end in intervals:
        # Subscriptions falling in this week's window
        week_subs = base_qs.filter(
            next_invoice_date__gte=w_start,
            next_invoice_date__lte=w_end,
        ).order_by("next_invoice_date")

        # Database Sum aggregation for projected revenue
        week_amount = week_subs.aggregate(total=Sum("plan__price"))["total"] or Decimal("0.00")
        subs_list = list(week_subs)

        grand_total_subs += len(subs_list)
        grand_total_amount += week_amount

        weeks.append({
            "title": title,
            "start": w_start,
            "end": w_end,
            "subscriptions": subs_list,
            "count": len(subs_list),
            "projected_total": week_amount,
        })

    context = {
        "weeks": weeks,
        "grand_total_subs": grand_total_subs,
        "grand_total_amount": grand_total_amount,
        "today": today,
        "end_date": end_date,
        "is_internal_staff": is_internal_staff,
    }
    return render(request, "portal/billing_calendar.html", context)


# ==============================================================================
# 7. STAFF-ONLY CUSTOMER DIRECTORY (PAGINATED)
# ==============================================================================
@role_required(User.ROLE_ADMIN, User.ROLE_STAFF)
def customer_list_view(request):
    """
    Staff-only Customer Directory with search and pagination.
    Uses database annotation to calculate:
      - Active subscriptions count
      - Total subscriptions count
      - Total invoices count
    Supports keyword filtering by customer email or name.
    """
    search_query = request.GET.get("q", "").strip()

    customers_qs = (
        User.objects
        .filter(role=User.ROLE_CUSTOMER)
        .annotate(
            active_subs_count=Count(
                "subscriptions",
                filter=Q(subscriptions__status=Subscription.STATUS_ACTIVE),
                distinct=True
            ),
            total_subs_count=Count("subscriptions", distinct=True),
            invoices_count=Count("subscriptions__invoices", distinct=True),
        )
        .order_by("-date_joined")
    )

    if search_query:
        customers_qs = customers_qs.filter(
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )

    # 10 customers per page with Django Paginator
    paginator = Paginator(customers_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "search_query": search_query,
        "total_customers": paginator.count,
    }
    return render(request, "portal/customer_list.html", context)


# ==============================================================================
# 8. STAFF-ONLY CUSTOMER DETAIL VIEW (PAGINATED)
# ==============================================================================
@role_required(User.ROLE_ADMIN, User.ROLE_STAFF)
def customer_detail_view(request, customer_id):
    """
    Staff-only Comprehensive Customer Profile.
    Inspects a customer's complete account history:
      - Active and historical subscriptions (select_related plan)
      - Invoices with status, balance due, and dates (select_related subscription__plan)
      - Recorded payment receipts (select_related invoice)
    Calculates total billed, total paid, and net balance via database Sum aggregation.
    """
    customer = get_object_or_404(User, id=customer_id, role=User.ROLE_CUSTOMER)

    # 1. Customer's subscriptions
    subscriptions = (
        customer.subscriptions
        .select_related("plan")
        .order_by("-created_at")
    )

    # 2. Customer's invoices
    invoices = (
        Invoice.objects
        .select_related("subscription__plan")
        .filter(subscription__customer=customer)
        .order_by("-created_at")
    )

    # 3. Customer's payments
    payments = (
        Payment.objects
        .select_related("invoice")
        .filter(invoice__subscription__customer=customer)
        .order_by("-date", "-created_at")
    )

    # 4. Financial totals using database Sum aggregation
    total_invoiced = invoices.aggregate(total=Sum("total"))["total"] or Decimal("0.00")
    total_paid = payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    total_outstanding = max(Decimal("0.00"), total_invoiced - total_paid)

    active_subs_count = subscriptions.filter(status=Subscription.STATUS_ACTIVE).count()
    overdue_invoices_count = invoices.overdue().count()

    context = {
        "customer": customer,
        "subscriptions": subscriptions,
        "invoices": invoices,
        "payments": payments,
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "total_outstanding": total_outstanding,
        "active_subs_count": active_subs_count,
        "overdue_invoices_count": overdue_invoices_count,
    }
    return render(request, "portal/customer_detail.html", context)
