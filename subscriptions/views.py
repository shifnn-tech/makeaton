"""
subscriptions/views.py
======================
Purpose:
    Subscription views for customers and staff.
    Uses filter_by_user helper to guarantee that customers only see their own subscriptions.
    Provides customer plan subscribing and staff status transitions.
"""

from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from accounts.utils import filter_by_user
from accounts.decorators import role_required
from catalog.models import Plan
from .models import Subscription
from billing.services import generate_invoice


@login_required
def subscription_list_view(request):
    """
    Lists subscriptions.
    - Customers see only their own subscriptions.
    - Staff / Admin see all organization subscriptions.
    """
    queryset = Subscription.objects.select_related("customer", "plan").all()
    subscriptions = filter_by_user(queryset, request.user, user_field="customer")

    return render(
        request,
        "subscriptions/subscription_list.html",
        {"subscriptions": subscriptions},
    )


@login_required
def subscription_detail_view(request, subscription_id):
    """
    Displays single subscription details along with its line items.
    Enforces user-level security via filter_by_user.
    Provides transition options for Staff/Admin.
    """
    queryset = (
        Subscription.objects
        .select_related("customer", "plan")
        .prefetch_related("lines__product", "lines__tax", "invoices")
    )
    scoped_queryset = filter_by_user(queryset, request.user, user_field="customer")
    subscription = get_object_or_404(scoped_queryset, id=subscription_id)

    # Allowed status transitions for Staff / Admin
    allowed_transitions = subscription.ALLOWED_TRANSITIONS.get(subscription.status, [])

    return render(
        request,
        "subscriptions/subscription_detail.html",
        {
            "subscription": subscription,
            "allowed_transitions": allowed_transitions,
            "invoices": subscription.invoices.all(),
        },
    )


@login_required
def subscribe_plan_view(request, plan_id):
    """
    Customer action: Subscribes the logged-in customer to a plan.
    Creates an Active subscription and automatically generates the first invoice.
    """
    plan = get_object_or_404(Plan, id=plan_id)
    today = timezone.localdate()

    if request.method == "POST":
        subscription = Subscription.objects.create(
            customer=request.user,
            plan=plan,
            start_date=today,
            status=Subscription.STATUS_ACTIVE,
            payment_terms="Immediate",
            next_invoice_date=today,
        )

        # Generate first invoice
        invoice = generate_invoice(subscription)

        messages.success(
            request,
            f"Congratulations! You have successfully subscribed to the {plan.name} plan. "
            f"Subscription {subscription.number} is now Active."
        )
        return redirect("subscriptions:detail", subscription_id=subscription.id)

    return redirect("catalog:plan_list")


@role_required("admin", "staff")
def subscription_change_status_view(request, subscription_id, target_status):
    """
    Staff/Admin action: Transitions a subscription status across the finite state machine.
    """
    subscription = get_object_or_404(Subscription, id=subscription_id)

    if request.method == "POST":
        try:
            subscription.change_status(target_status)
            messages.success(
                request,
                f"Subscription {subscription.number} status transitioned to '{target_status}' successfully."
            )
        except Exception as e:
            messages.error(request, f"Error changing status: {e}")

    return redirect("subscriptions:detail", subscription_id=subscription.id)


@role_required("admin", "staff")
def subscription_generate_invoice_view(request, subscription_id):
    """
    Staff/Admin action: Manually triggers generation of an invoice for this subscription.
    """
    subscription = get_object_or_404(Subscription, id=subscription_id)

    if request.method == "POST":
        invoice = generate_invoice(subscription)
        if invoice:
            messages.success(request, f"Invoice {invoice.number} generated successfully!")
            return redirect("billing:detail", invoice_id=invoice.id)
        else:
            messages.warning(request, "Invoice could not be generated (already billed for current cycle).")

    return redirect("subscriptions:detail", subscription_id=subscription.id)
