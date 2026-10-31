"""
billing/services.py
===================
Purpose:
    Core business logic and domain services for recurring billing generation.
    Contains the atomic transaction engine for automated subscription invoicing.
"""

from decimal import Decimal
from datetime import timedelta
import logging
from django.db import transaction
from django.utils import timezone
from subscriptions.models import Subscription
from billing.models import Invoice, InvoiceLine

logger = logging.getLogger(__name__)


@transaction.atomic
def generate_invoice(subscription: Subscription, period_start=None):
    """
    Generates an Invoice and InvoiceLines for a given Subscription.
    
    This function is wrapped in `@transaction.atomic` to guarantee that all DB
    operations (invoice creation, line copying, tax calculations, and advancing
    subscription dates) succeed together or rollback completely on error.
    """
    if period_start is None:
        period_start = subscription.next_invoice_date or subscription.start_date or timezone.localdate()

    # Step 1: Idempotency Guard (Prevents double billing the same period)
    existing_invoice = Invoice.objects.filter(subscription=subscription, period_start=period_start).first()
    if existing_invoice:
        logger.warning(f"Invoice already exists for subscription {subscription.number} on period {period_start}")
        return existing_invoice

    # Step 2: Determine Billing Period Dates
    billing_period = getattr(subscription.plan, "billing_period", "monthly")
    if billing_period == "daily":
        period_end = period_start + timedelta(days=1)
    elif billing_period == "weekly":
        period_end = period_start + timedelta(weeks=1)
    elif billing_period == "yearly":
        period_end = period_start + timedelta(days=365)
    else:  # default monthly
        period_end = period_start + timedelta(days=30)

    due_date = period_start + timedelta(days=14)

    # Step 3: Create Invoice Record
    invoice = Invoice.objects.create(
        subscription=subscription,
        period_start=period_start,
        period_end=period_end,
        due_date=due_date,
        status=Invoice.STATUS_CONFIRMED,
        subtotal=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        total=Decimal("0.00"),
    )

    # Step 4: Copy Subscription Lines / Plan to Invoice Lines
    subtotal = Decimal("0.00")
    total_tax = Decimal("0.00")
    lines = list(subscription.lines.select_related("product", "tax").all())

    if lines:
        for line in lines:
            line_subtotal = Decimal(str(line.quantity)) * Decimal(str(line.unit_price))
            subtotal += line_subtotal

            tax_rate = Decimal(str(line.tax.rate)) if line.tax else Decimal("0.00")
            line_tax = (line_subtotal * (tax_rate / Decimal("100"))).quantize(Decimal("0.01"))
            total_tax += line_tax

            InvoiceLine.objects.create(
                invoice=invoice,
                product=line.product,
                description=f"{line.product.name} ({subscription.plan.name})",
                quantity=line.quantity,
                unit_price=line.unit_price,
                tax_rate=tax_rate,
                amount=line_subtotal,
            )
    else:
        # Fallback to subscription plan base price if no itemized lines exist
        plan_price = Decimal(str(subscription.plan.price))
        subtotal = plan_price
        tax_rate = Decimal("18.00")  # Standard default VAT / GST
        total_tax = (plan_price * (tax_rate / Decimal("100"))).quantize(Decimal("0.01"))

        InvoiceLine.objects.create(
            invoice=invoice,
            product=None,
            description=f"Subscription Plan - {subscription.plan.name}",
            quantity=1,
            unit_price=plan_price,
            tax_rate=tax_rate,
            amount=plan_price,
        )

    # Step 5: Compute Final Invoice Totals
    invoice.subtotal = subtotal
    invoice.tax_amount = total_tax
    invoice.discount_amount = Decimal("0.00")
    invoice.total = subtotal + total_tax
    invoice.save(update_fields=["subtotal", "tax_amount", "discount_amount", "total", "updated_at"])

    # Step 6: Advance Next Invoice Date on Subscription
    subscription.next_invoice_date = period_end
    subscription.save(update_fields=["next_invoice_date", "updated_at"])

    logger.info(f"Successfully generated invoice {invoice.number} for subscription {subscription.number}")
    return invoice
