"""
billing/views.py
================
Purpose:
    Invoice, payment processing, analytics, and PDF views for BrightLoop.
    Implements RBAC (Role-Based Access Control) using accounts.decorators.role_required
    and strict data-scoping via accounts.utils.filter_by_user.
"""

import io
import logging
from decimal import Decimal
from django.db import models
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from accounts.decorators import role_required
from accounts.utils import filter_by_user
from .models import Invoice, Payment
from .forms import PaymentForm

logger = logging.getLogger(__name__)

# Check if xhtml2pdf is available in the environment
try:
    from xhtml2pdf import pisa
    XHTML2PDF_AVAILABLE = True
except ImportError:
    XHTML2PDF_AVAILABLE = False


@login_required
def invoice_list_view(request):
    """
    Lists all invoices accessible to the logged-in user:
      - Customers see strictly their own invoices.
      - Staff and Admin see all organization billing records.
    """
    queryset = (
        Invoice.objects
        .select_related("subscription__customer", "subscription__plan")
        .order_by("-created_at")
    )
    invoices = filter_by_user(queryset, request.user, user_field="subscription__customer")

    return render(request, "billing/list.html", {"invoices": invoices})


@login_required
def invoice_outstanding_view(request):
    """
    Displays outstanding and overdue invoices with badges and balance due.
    Allows filtering by status ('all', 'overdue', 'outstanding').
    """
    filter_mode = request.GET.get("filter", "all")
    base_qs = (
        Invoice.objects
        .select_related("subscription__customer", "subscription__plan")
        .order_by("due_date")
    )
    scoped_qs = filter_by_user(base_qs, request.user, user_field="subscription__customer")

    if filter_mode == "overdue":
        invoices = scoped_qs.overdue()
    elif filter_mode == "outstanding":
        invoices = scoped_qs.outstanding()
    else:
        # Combined: either overdue or confirmed with balance due
        today = timezone.localdate()
        invoices = (
            scoped_qs
            .filter(status__in=[Invoice.STATUS_CONFIRMED, "Confirmed", Invoice.STATUS_DRAFT, "Draft"])
            .exclude(status__in=[Invoice.STATUS_PAID, "Paid"])
        )

    return render(
        request,
        "billing/outstanding.html",
        {
            "invoices": invoices,
            "filter_mode": filter_mode,
        },
    )


@login_required
def invoice_detail_view(request, invoice_id: int):
    """
    Detailed statement view with itemized lines, discounts, taxes, totals,
    recorded payment receipts, balance due, and action triggers.
    """
    base_qs = (
        Invoice.objects
        .select_related("subscription__customer", "subscription__plan", "discount")
        .prefetch_related("lines__product", "payments__recorded_by")
    )
    scoped_qs = filter_by_user(base_qs, request.user, user_field="subscription__customer")
    invoice = get_object_or_404(scoped_qs, id=invoice_id)

    return render(request, "billing/detail.html", {"invoice": invoice})


@role_required("admin", "staff")
def record_payment_view(request, invoice_id: int):
    """
    Staff / Admin view to record a full or partial payment against an invoice.
    Enforces balance limits and updates invoice status atomically upon settlement.
    """
    invoice = get_object_or_404(
        Invoice.objects.select_related("subscription__customer", "subscription__plan"),
        id=invoice_id,
    )

    if invoice.balance_due <= Decimal("0.00"):
        messages.info(request, f"Invoice {invoice.number} is already fully paid.")
        return redirect("billing:detail", invoice_id=invoice.id)

    if request.method == "POST":
        form = PaymentForm(request.POST, invoice=invoice, user=request.user)
        if form.is_valid():
            payment = form.save()
            messages.success(
                request,
                f"Payment #{payment.id} for ${payment.amount:.2f} recorded successfully."
            )
            return redirect("billing:detail", invoice_id=invoice.id)
        else:
            messages.error(request, "Please correct the payment form errors below.")
    else:
        form = PaymentForm(invoice=invoice, user=request.user)

    return render(
        request,
        "billing/record_payment.html",
        {
            "form": form,
            "invoice": invoice,
        },
    )


@role_required("admin", "staff")
def confirm_invoice_view(request, invoice_id: int):
    """
    Action endpoint to move an invoice from DRAFT to CONFIRMED.
    """
    invoice = get_object_or_404(Invoice, id=invoice_id)

    if request.method == "POST":
        try:
            invoice.confirm()
            messages.success(request, f"Invoice {invoice.number} has been confirmed.")
        except ValidationError as exc:
            messages.error(request, f"Cannot confirm invoice: {exc}")

    return redirect("billing:detail", invoice_id=invoice.id)


@login_required
def payment_history_view(request):
    """
    Searchable and filterable payment history audit log.
    - Staff/Admin see organization-wide transactions.
    - Customers see only payments related to their own invoices.
    """
    queryset = (
        Payment.objects
        .select_related("invoice__subscription__customer", "invoice__subscription__plan", "recorded_by")
        .order_by("-date", "-created_at")
    )
    payments = filter_by_user(queryset, request.user, user_field="invoice__subscription__customer")

    # Filter parameters
    method = request.GET.get("method")
    search_q = request.GET.get("q")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    if method:
        payments = payments.filter(method=method)
    if search_q:
        payments = payments.filter(
            models.Q(invoice__number__icontains=search_q)
            | models.Q(reference__icontains=search_q)
            | models.Q(invoice__subscription__customer__email__icontains=search_q)
        )
    if date_from:
        payments = payments.filter(date__gte=date_from)
    if date_to:
        payments = payments.filter(date__lte=date_to)

    return render(
        request,
        "billing/payment_history.html",
        {
            "payments": payments,
            "selected_method": method,
            "search_q": search_q or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "methods": Payment.METHOD_CHOICES,
        },
    )


@login_required
def invoice_pdf_view(request, invoice_id: int):
    """
    Generates and downloads a PDF of the invoice statement using xhtml2pdf.
    Falls back to a print-friendly HTML view with @media print CSS if PDF rendering fails.
    """
    base_qs = (
        Invoice.objects
        .select_related("subscription__customer", "subscription__plan", "discount")
        .prefetch_related("lines__product", "payments")
    )
    scoped_qs = filter_by_user(base_qs, request.user, user_field="subscription__customer")
    invoice = get_object_or_404(scoped_qs, id=invoice_id)

    context = {
        "invoice": invoice,
        "generated_at": timezone.now(),
    }

    # Attempt PDF rendering with xhtml2pdf
    if XHTML2PDF_AVAILABLE:
        try:
            html_content = render_to_string("billing/pdf.html", context)
            pdf_buffer = io.BytesIO()
            pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)

            if not pisa_status.err:
                response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
                response["Content-Disposition"] = f'attachment; filename="Invoice-{invoice.number}.pdf"'
                return response
            else:
                logger.error(f"xhtml2pdf error generating PDF for invoice {invoice.number}")
        except Exception as exc:
            logger.exception(f"Exception during PDF generation: {exc}")

    # Graceful fallback: render print-friendly HTML stylesheet view
    messages.info(request, "PDF rendered using print-friendly format. Use your browser's Print to PDF option.")
    context["fallback_print"] = True
    return render(request, "billing/pdf.html", context)
