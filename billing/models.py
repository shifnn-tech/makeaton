"""
billing/models.py
=================
Purpose:
    Billing, Invoicing, and Payment data models for the BrightLoop project.
    Enforces financial integrity:
      - Unique constraint on (subscription, period_start) to prevent duplicate billing
      - Strict finite state machine for invoice statuses (DRAFT -> CONFIRMED -> PAID)
      - Dynamic financial properties for amount_paid and balance_due
      - QuerySet/Manager helpers for overdue and outstanding invoices
      - Strict payment validation (strictly positive, cannot exceed remaining invoice balance)
      - Discount calculations with validation (fixed vs percentage, validity periods, usage limits)
"""

import uuid
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from catalog.models import Product
from subscriptions.models import Subscription


class Discount(models.Model):
    """
    Promotional or negotiated discount applied to an invoice.
    Supports fixed currency reductions or percentage-based deductions.
    """

    TYPE_FIXED = "FIXED"
    TYPE_PERCENTAGE = "PERCENTAGE"

    TYPE_CHOICES = (
        (TYPE_FIXED, _("Fixed Amount")),
        (TYPE_PERCENTAGE, _("Percentage")),
    )

    name = models.CharField(
        max_length=150,
        help_text=_("Display title of the discount (e.g. VIP Partner Discount)."),
    )
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text=_("Unique redemption code (e.g. SAVE20)."),
    )
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_FIXED,
        help_text=_("Type of deduction: FIXED currency amount or PERCENTAGE rate."),
    )
    value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Discount amount in currency or percentage value (0-100)."),
    )
    valid_from = models.DateField(
        null=True,
        blank=True,
        help_text=_("Start date of discount validity window."),
    )
    valid_to = models.DateField(
        null=True,
        blank=True,
        help_text=_("End date of discount validity window."),
    )
    usage_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_("Maximum number of times this discount can be redeemed overall (None for unlimited)."),
    )
    times_used = models.PositiveIntegerField(
        default=0,
        help_text=_("Current count of successful redemptions."),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Toggles whether this discount is currently eligible for application."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Discount")
        verbose_name_plural = _("Discounts")

    def __str__(self):
        suffix = "%" if self.type == self.TYPE_PERCENTAGE else "$"
        return f"{self.name} ({self.code}) - {self.value}{suffix}"

    def clean(self):
        """
        Model validation:
          - Percentage must be between 0 and 100.
          - Fixed amount must be strictly greater than 0.
          - valid_to must be >= valid_from when both dates are provided.
        """
        super().clean()

        if self.type == self.TYPE_PERCENTAGE:
            if self.value is not None and (self.value < Decimal("0.00") or self.value > Decimal("100.00")):
                raise ValidationError({"value": _("Percentage discount value must be between 0.00 and 100.00.")})
        elif self.type == self.TYPE_FIXED:
            if self.value is not None and self.value <= Decimal("0.00"):
                raise ValidationError({"value": _("Fixed discount value must be strictly greater than zero.")})

        if self.valid_from and self.valid_to:
            if self.valid_to < self.valid_from:
                raise ValidationError({"valid_to": _("Validity end date (valid_to) must be on or after start date (valid_from).")})

    def calculate(self, amount: Decimal, on_date=None) -> Decimal:
        """
        Calculates the discount amount against a target gross amount.
        Returns 0 if:
          - Discount is inactive
          - on_date falls outside the valid_from / valid_to date range
          - usage_limit has been reached
          - target amount is non-positive
        The computed deduction will never exceed the target amount.
        """
        if not self.is_active:
            return Decimal("0.00")

        if self.usage_limit is not None and self.times_used >= self.usage_limit:
            return Decimal("0.00")

        if on_date is None:
            on_date = timezone.localdate()

        if self.valid_from and on_date < self.valid_from:
            return Decimal("0.00")

        if self.valid_to and on_date > self.valid_to:
            return Decimal("0.00")

        if amount <= Decimal("0.00"):
            return Decimal("0.00")

        if self.type == self.TYPE_PERCENTAGE:
            deduction = (amount * self.value) / Decimal("100")
            quantized = deduction.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            quantized = self.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return min(amount, quantized)


class InvoiceQuerySet(models.QuerySet):
    """
    Custom QuerySet for Invoice model providing domain-specific queries.
    """

    def overdue(self):
        """
        Returns all invoices where due_date < today AND status != PAID.
        Calculated dynamically via SQL query.
        """
        today = timezone.localdate()
        return self.filter(due_date__lt=today).exclude(status__in=[Invoice.STATUS_PAID, "Paid"])

    def outstanding(self):
        """
        Returns all invoices where status == CONFIRMED and balance_due > 0.
        Uses database annotation to compare invoice total against sum of recorded payments.
        """
        return (
            self.filter(status__in=[Invoice.STATUS_CONFIRMED, "Confirmed"])
            .annotate(settled_payments=Coalesce(Sum("payments__amount"), Value(Decimal("0.00"))))
            .filter(total__gt=F("settled_payments"))
        )

    def unpaid(self):
        """Returns all confirmed or draft invoices that have not been settled."""
        return self.exclude(status__in=[Invoice.STATUS_PAID, "Paid"])


class InvoiceManager(models.Manager):
    """
    Custom manager exposing custom QuerySet methods directly on Invoice.objects.
    """

    def get_queryset(self):
        return InvoiceQuerySet(self.model, using=self._db)

    def overdue(self):
        return self.get_queryset().overdue()

    def outstanding(self):
        return self.get_queryset().outstanding()

    def unpaid(self):
        return self.get_queryset().unpaid()


class Invoice(models.Model):
    """
    Itemized billing statement generated for a specific subscription period.
    """

    STATUS_DRAFT = "DRAFT"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_PAID = "PAID"

    STATUS_CHOICES = (
        (STATUS_DRAFT, _("Draft")),
        (STATUS_CONFIRMED, _("Confirmed")),
        (STATUS_PAID, _("Paid")),
    )

    ALLOWED_TRANSITIONS = {
        STATUS_DRAFT: [STATUS_CONFIRMED],
        STATUS_CONFIRMED: [STATUS_PAID],
        STATUS_PAID: [],  # Terminal state
        # Also support titlecase transitions for backward compatibility with existing data
        "Draft": [STATUS_CONFIRMED, "Confirmed"],
        "Confirmed": [STATUS_PAID, "Paid"],
        "Paid": [],
        "Cancelled": [],
    }

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="invoices",
        help_text=_("Subscription associated with this bill."),
    )

    number = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        help_text=_("Unique auto-generated invoice reference number (e.g. INV-202610-0012)."),
    )

    period_start = models.DateField(
        help_text=_("Beginning of this billing cycle."),
    )
    period_end = models.DateField(
        help_text=_("Conclusion of this billing cycle."),
    )
    issue_date = models.DateField(
        default=timezone.localdate,
        help_text=_("Date this invoice was officially issued."),
    )
    due_date = models.DateField(
        help_text=_("Payment deadline date."),
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )

    discount = models.ForeignKey(
        Discount,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
        help_text=_("Optional discount coupon applied to this invoice."),
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Gross total of all invoice line items before discounts and taxes."),
    )
    discount_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Total discount deducted from the subtotal."),
    )
    tax_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Total sales tax applied across all line items."),
    )
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Final payable balance (subtotal - discount_total + tax_total)."),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = InvoiceManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Invoice")
        verbose_name_plural = _("Invoices")
        constraints = [
            # Invariant: Prevents double-billing the same subscription for the same billing cycle
            models.UniqueConstraint(
                fields=["subscription", "period_start"],
                name="unique_invoice_per_subscription_period",
            )
        ]

    def __str__(self):
        return f"{self.number} ({self.subscription.customer.email}) - ${self.total} [{self.status}]"

    def save(self, *args, **kwargs):
        # Auto-generate unique human-readable invoice reference number
        if not self.number:
            date_prefix = timezone.now().strftime("%Y%m")
            random_suffix = uuid.uuid4().hex[:6].upper()
            self.number = f"INV-{date_prefix}-{random_suffix}"
        super().save(*args, **kwargs)

    # --------------------------------------------------------------------------
    # Backward Compatibility Aliases for Templates & External Code
    # --------------------------------------------------------------------------
    @property
    def invoice_number(self) -> str:
        """Alias for number."""
        return self.number

    @invoice_number.setter
    def invoice_number(self, value: str):
        self.number = value

    @property
    def discount_amount(self) -> Decimal:
        """Alias for discount_total."""
        return self.discount_total

    @discount_amount.setter
    def discount_amount(self, value: Decimal):
        self.discount_total = value

    @property
    def tax_amount(self) -> Decimal:
        """Alias for tax_total."""
        return self.tax_total

    @tax_amount.setter
    def tax_amount(self, value: Decimal):
        self.tax_total = value

    # --------------------------------------------------------------------------
    # Status Transition Methods
    # --------------------------------------------------------------------------
    def confirm(self, save: bool = True):
        """
        Transitions invoice from DRAFT to CONFIRMED.
        Raises ValidationError on invalid transition.
        """
        if self.status not in [self.STATUS_DRAFT, "Draft"]:
            raise ValidationError(
                _(f"Invalid status transition. Cannot confirm invoice from status '{self.status}'.")
            )
        self.status = self.STATUS_CONFIRMED
        if save:
            self.save(update_fields=["status", "updated_at"])

    def mark_paid(self, save: bool = True):
        """
        Transitions invoice from CONFIRMED to PAID.
        Raises ValidationError on invalid transition.
        """
        if self.status not in [self.STATUS_CONFIRMED, "Confirmed"]:
            raise ValidationError(
                _(f"Invalid status transition. Cannot mark invoice as paid from status '{self.status}'.")
            )
        self.status = self.STATUS_PAID
        if save:
            self.save(update_fields=["status", "updated_at"])

    def change_status(self, new_status: str, save: bool = True):
        """
        Validates transition against ALLOWED_TRANSITIONS and moves to target status.
        """
        allowed = self.ALLOWED_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValidationError(
                _(f"Invalid invoice transition from '{self.status}' to '{new_status}'. "
                  f"Allowed target states are: {allowed or 'None (Terminal)'}")
            )
        self.status = new_status
        if save:
            self.save(update_fields=["status", "updated_at"])

    # --------------------------------------------------------------------------
    # Dynamic Financial Properties
    # --------------------------------------------------------------------------
    @property
    def amount_paid(self) -> Decimal:
        """Sum of all settled payments recorded against this invoice."""
        aggregated = self.payments.aggregate(total=Sum("amount"))
        paid = aggregated["total"] or Decimal("0.00")
        return Decimal(str(paid)).quantize(Decimal("0.01"))

    @property
    def balance_due(self) -> Decimal:
        """Remaining outstanding amount on this invoice (total minus amount_paid)."""
        balance = self.total - self.amount_paid
        return max(Decimal("0.00"), balance).quantize(Decimal("0.01"))

    @property
    def is_overdue(self) -> bool:
        """True if invoice due_date is in the past and status is not PAID."""
        return self.status not in [self.STATUS_PAID, "Paid"] and self.due_date < timezone.localdate()


class InvoiceLine(models.Model):
    """
    Itemized charge on an Invoice.
    """

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    product = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice_lines",
    )
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Tax rate applied as percentage (e.g. 18.00)."),
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Line subtotal before tax."),
    )

    class Meta:
        verbose_name = _("Invoice Line")
        verbose_name_plural = _("Invoice Lines")

    def __str__(self):
        return f"{self.description} ({self.quantity} @ ${self.unit_price})"

    @property
    def line_subtotal(self) -> Decimal:
        """Line subtotal: quantity * unit_price."""
        return Decimal(self.quantity) * self.unit_price

    @property
    def line_tax(self) -> Decimal:
        """Line tax: line_subtotal * (tax_rate / 100), rounded to 2 decimals with ROUND_HALF_UP."""
        tax = (self.line_subtotal * self.tax_rate) / Decimal("100")
        return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def line_total(self) -> Decimal:
        """Line total: line_subtotal + line_tax."""
        return self.line_subtotal + self.line_tax

    def save(self, *args, **kwargs):
        if not self.amount:
            self.amount = self.line_subtotal
        super().save(*args, **kwargs)


class Payment(models.Model):
    """
    Financial receipt applied toward settling an Invoice.
    """

    METHOD_CASH = "CASH"
    METHOD_CARD = "CARD"
    METHOD_BANK_TRANSFER = "BANK_TRANSFER"
    METHOD_UPI = "UPI"
    METHOD_OTHER = "OTHER"

    # Compatibility alias for seed_data
    METHOD_CREDIT_CARD = METHOD_CARD

    METHOD_CHOICES = (
        (METHOD_CASH, _("Cash")),
        (METHOD_CARD, _("Card")),
        (METHOD_BANK_TRANSFER, _("Bank Transfer")),
        (METHOD_UPI, _("UPI")),
        (METHOD_OTHER, _("Other")),
    )

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text=_("Payment amount in currency."),
    )
    date = models.DateField(
        default=timezone.localdate,
        help_text=_("Date this payment was executed."),
    )
    method = models.CharField(
        max_length=30,
        choices=METHOD_CHOICES,
        default=METHOD_CARD,
    )
    reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Transaction reference number or gateway identifier."),
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recorded_payments",
        help_text=_("Staff member or user who logged this payment transaction."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")

    def __str__(self):
        return f"Payment #{self.id} for {self.invoice.number} - ${self.amount} via {self.get_method_display()}"

    # --------------------------------------------------------------------------
    # Backward Compatibility Aliases for Seed Data & External Code
    # --------------------------------------------------------------------------
    @property
    def payment_date(self):
        """Alias for date."""
        return self.date

    @payment_date.setter
    def payment_date(self, value):
        self.date = value

    @property
    def note(self):
        return self.reference

    @note.setter
    def note(self, value):
        self.reference = value

    def clean(self):
        """
        Payment validation:
          1. Amount must be strictly greater than zero.
          2. Amount cannot exceed the remaining balance due on the invoice.
             When editing an existing payment, excludes its own previous amount.
        """
        super().clean()

        if self.amount is not None and self.amount <= Decimal("0.00"):
            raise ValidationError({"amount": _("Payment amount must be strictly greater than zero.")})

        if self.invoice_id and self.amount is not None:
            # Exclude self if updating an existing payment
            other_payments = self.invoice.payments.exclude(pk=self.pk).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            current_balance = self.invoice.total - other_payments

            if self.amount > current_balance:
                raise ValidationError({
                    "amount": _(
                        f"Payment amount (${self.amount}) exceeds the remaining invoice balance (${current_balance})."
                    )
                })

    def save(self, *args, **kwargs):
        # Enforce model validation on save
        self.full_clean()
        super().save(*args, **kwargs)

        # Automatically mark invoice as PAID if balance reaches zero and invoice is CONFIRMED
        if self.invoice.balance_due <= Decimal("0.00") and self.invoice.status in [Invoice.STATUS_CONFIRMED, "Confirmed"]:
            self.invoice.status = Invoice.STATUS_PAID
            self.invoice.save(update_fields=["status", "updated_at"])
