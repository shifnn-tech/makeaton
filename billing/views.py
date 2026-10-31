"""
billing/views.py
================
Purpose:
    Invoice views for customers and staff.
    Uses filter_by_user to ensure customers only view their own invoices.
    Supports recording payments directly in the portal.
"""

from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from accounts.utils import filter_by_user
from .models import Invoice, Payment


@login_required
def invoice_list_view(request):
    """
    Lists invoices.
    - Customers see only their own invoices.
    - Staff / Admin see all organization invoices.
    """
    queryset = Invoice.objects.select_related("subscription__customer", "subscription__plan").all()
    invoices = filter_by_user(queryset, request.user, user_field="subscription__customer")

    return render(request, "billing/invoice_list.html", {"invoices": invoices})


@login_required
def invoice_detail_view(request, invoice_id):
    """
    Displays single invoice detail with line items and payment breakdown.
    Scoped to user permissions.
    """
    queryset = (
        Invoice.objects
        .select_related("subscription__customer", "subscription__plan")
        .prefetch_related("lines__product", "payments")
    )
    scoped_queryset = filter_by_user(queryset, request.user, user_field="subscription__customer")
    invoice = get_object_or_404(scoped_queryset, id=invoice_id)

    return render(request, "billing/invoice_detail.html", {"invoice": invoice})


@login_required
def invoice_pay_view(request, invoice_id):
    """
    Processes a simulated payment against an invoice.
    Allows customers (for their own invoice) and staff/admin to settle the balance.
    """
    queryset = Invoice.objects.select_related("subscription__customer")
    scoped_queryset = filter_by_user(queryset, request.user, user_field="subscription__customer")
    invoice = get_object_or_404(scoped_queryset, id=invoice_id)

    if invoice.balance_due <= Decimal("0.00"):
        messages.info(request, f"Invoice {invoice.number} is already fully paid.")
        return redirect("billing:detail", invoice_id=invoice.id)

    if request.method == "POST":
        amount_to_pay = invoice.balance_due
        payment = Payment.objects.create(
            invoice=invoice,
            amount=amount_to_pay,
            method=Payment.METHOD_CREDIT_CARD,
            note="Settled via BrightLoop Online Portal",
        )
        messages.success(
            request,
            f"Payment of ${payment.amount} processed successfully! Invoice {invoice.number} marked as Paid."
        )

    return redirect("billing:detail", invoice_id=invoice.id)
