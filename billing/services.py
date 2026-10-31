"""
billing/services.py
===================
Purpose:
    Domain services and business logic for automated recurring billing.
    Provides generate_invoice() with atomic transactions, idempotency guards,
    discount deductions, tax calculations, and dry-run simulation.
"""

import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from subscriptions.models import Subscription
from .models import Discount, Invoice, InvoiceLine

logger = logging.getLogger(__name__)


class DuplicateInvoiceError(Exception):
    """
    Raised when an invoice has already been generated for a subscription
    for the specified billing period_start.
    """
    pass


@transaction.atomic
def generate_invoice(
    subscription: Subscription,
    period_start=None,
    period_end=None,
    dry_run: bool = False,
    discount: Discount = None,
    status: str = Invoice.STATUS_CONFIRMED,
    raise_on_duplicate: bool = False,
) -> Invoice:
    """
    Generates an itemized Invoice and InvoiceLines for a given Subscription.

    Parameters:
        subscription (Subscription): Active customer subscription contract.
        period_start (date, optional): Billing cycle start date. Defaults to
            subscription.next_invoice_date or subscription.start_date.
        period_end (date, optional): Billing cycle end date. Calculated automatically
            from subscription.plan.billing_period if omitted.
        dry_run (bool): If True, computes the complete invoice and lines in-memory
            without persisting any records to the database.
        discount (Discount, optional): Eligible promotional discount to apply.
        status (str): Initial invoice status (defaults to CONFIRMED).
        raise_on_duplicate (bool): If True, raises DuplicateInvoiceError when an
            invoice already exists for (subscription, period_start); otherwise returns
            the existing invoice idempotently.

    Returns:
        Invoice: The generated Invoice instance (persisted if dry_run=False, in-memory if dry_run=True).

    Raises:
        DuplicateInvoiceError: If raise_on_duplicate=True and an invoice already exists.
    """
    # --------------------------------------------------------------------------
    # 1. Determine Billing Period Dates
    # --------------------------------------------------------------------------
    if period_start is None:
        period_start = subscription.next_invoice_date or subscription.start_date or timezone.localdate()

    # --------------------------------------------------------------------------
    # 2. Idempotency Guard: Prevent Duplicate Invoicing for the Same Period
    # --------------------------------------------------------------------------
    existing_invoice = Invoice.objects.filter(subscription=subscription, period_start=period_start).first()
    if existing_invoice:
        msg = f"Invoice already exists for subscription {subscription.number} and period start {period_start}."
        logger.warning(msg)
        if raise_on_duplicate:
            raise DuplicateInvoiceError(msg)
        return existing_invoice

    # Calculate period_end if not explicitly provided
    if period_end is None:
        billing_period = getattr(subscription.plan, "billing_period", "monthly")
        if billing_period == "daily":
            period_end = period_start + timedelta(days=1)
        elif billing_period == "weekly":
            period_end = period_start + timedelta(weeks=1)
        elif billing_period == "yearly":
            period_end = period_start + timedelta(days=365)
        else:  # monthly
            period_end = period_start + timedelta(days=30)

    # Determine due date based on subscription payment terms
    terms = (getattr(subscription, "payment_terms", "") or "").strip().lower()
    if "net" in terms:
        try:
            days = int("".join(filter(str.isdigit, terms)))
            due_date = period_start + timedelta(days=days)
        except ValueError:
            due_date = period_start + timedelta(days=14)
    elif "immediate" in terms:
        due_date = period_start
    else:
        due_date = period_start + timedelta(days=14)

    issue_date = timezone.localdate()

    # --------------------------------------------------------------------------
    # 3. Compile Itemized Line Items from Subscription
    # --------------------------------------------------------------------------
    raw_lines = []
    sub_lines = list(subscription.lines.select_related("product", "tax").all())

    if sub_lines:
        for s_line in sub_lines:
            tax_rate = s_line.tax.rate if s_line.tax else Decimal("0.00")
            raw_lines.append({
                "product": s_line.product,
                "description": f"{s_line.product.name} ({subscription.plan.name})",
                "quantity": s_line.quantity,
                "unit_price": s_line.unit_price,
                "tax_rate": tax_rate,
            })
    elif subscription.plan:
        raw_lines.append({
            "product": None,
            "description": f"{subscription.plan.name} - Recurring Subscription",
            "quantity": 1,
            "unit_price": subscription.plan.price,
            "tax_rate": Decimal("0.00"),
        })

    # --------------------------------------------------------------------------
    # 4. Compute Gross Subtotal
    # --------------------------------------------------------------------------
    subtotal = Decimal("0.00")
    for item in raw_lines:
        line_sub = Decimal(item["quantity"]) * item["unit_price"]
        item["line_subtotal"] = line_sub
        subtotal += line_sub

    # --------------------------------------------------------------------------
    # 5. Apply Eligible Discount
    # --------------------------------------------------------------------------
    discount_total = Decimal("0.00")
    applied_discount = discount

    if applied_discount:
        discount_total = applied_discount.calculate(subtotal, on_date=issue_date)

    # ==========================================================================
    # TAX CALCULATION POLICY:
    # --------------------------------------------------------------------------
    # Discounts are applied BEFORE sales tax is calculated.
    # In standard commercial accounting and statutory VAT/GST frameworks, tax is
    # assessed on the net taxable consideration received from the customer rather
    # than the undiscounted list price. This ensures customers are only taxed on
    # the amount actually charged.
    # ==========================================================================
    tax_total = Decimal("0.00")
    for item in raw_lines:
        line_sub = item["line_subtotal"]
        if subtotal > Decimal("0.00") and discount_total > Decimal("0.00"):
            # Allocate discount proportionally across line items
            line_discount = (line_sub / subtotal) * discount_total
            taxable_base = max(Decimal("0.00"), line_sub - line_discount)
        else:
            taxable_base = line_sub

        line_tax = (taxable_base * item["tax_rate"] / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        item["line_tax"] = line_tax
        tax_total += line_tax

    # Final payable balance: subtotal - discount_total + tax_total
    total = max(Decimal("0.00"), subtotal - discount_total + tax_total)

    # --------------------------------------------------------------------------
    # 6. Instantiate Invoice
    # --------------------------------------------------------------------------
    invoice = Invoice(
        subscription=subscription,
        period_start=period_start,
        period_end=period_end,
        issue_date=issue_date,
        due_date=due_date,
        status=status,
        discount=applied_discount,
        subtotal=subtotal,
        discount_total=discount_total,
        tax_total=tax_total,
        total=total,
    )

    # --------------------------------------------------------------------------
    # 7. Dry-Run Mode: Return In-Memory Representation Without Database Writes
    # --------------------------------------------------------------------------
    if dry_run:
        invoice.number = f"INV-DRYRUN-{uuid.uuid4().hex[:6].upper()}"
        invoice._dry_run_lines = [
            InvoiceLine(
                invoice=invoice,
                product=item["product"],
                description=item["description"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                tax_rate=item["tax_rate"],
                amount=item["line_subtotal"],
            )
            for item in raw_lines
        ]
        return invoice

    # --------------------------------------------------------------------------
    # 8. Persist Invoice, Line Items, and Update Counter/Dates
    # --------------------------------------------------------------------------
    invoice.save()

    for item in raw_lines:
        InvoiceLine.objects.create(
            invoice=invoice,
            product=item["product"],
            description=item["description"],
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            tax_rate=item["tax_rate"],
            amount=item["line_subtotal"],
        )

    # Increment discount usage limit only when actually saved
    if applied_discount and discount_total > Decimal("0.00"):
        applied_discount.times_used = F("times_used") + 1
        applied_discount.save(update_fields=["times_used"])
        applied_discount.refresh_from_db(fields=["times_used"])

    # Advance subscription's next_invoice_date
    subscription.next_invoice_date = period_end
    subscription.save(update_fields=["next_invoice_date", "updated_at"])

    logger.info(f"Generated invoice {invoice.number} for subscription {subscription.number}")
    return invoice
