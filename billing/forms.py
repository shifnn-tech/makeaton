"""
billing/forms.py
================
Purpose:
    Form definitions for recording and validating customer payments against invoices.
    Enforces atomic balance updates and partial-payment handling.
"""

from decimal import Decimal
from django import forms
from django.db import transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from .models import Payment, Invoice


class PaymentForm(forms.ModelForm):
    """
    ModelForm for recording partial or full payments against an Invoice.
    Shows the current outstanding balance and prevents overpayment.
    """

    class Meta:
        model = Payment
        fields = ["amount", "method", "reference", "date"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "method": forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={"class": "form-control", "placeholder": "Check #, Transaction ID, etc."}),
        }

    def __init__(self, *args, invoice: Invoice = None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice or getattr(self.instance, "invoice", None)
        self.user = user

        if self.invoice:
            self.current_balance_due = self.invoice.balance_due
            self.fields["amount"].help_text = (
                f"Outstanding balance: ${self.current_balance_due:.2f}. "
                f"Enter full or partial payment amount."
            )
            # Default amount to remaining balance if creating a new payment
            if not self.instance.pk and "amount" not in self.initial:
                self.initial["amount"] = self.current_balance_due
        else:
            self.current_balance_due = Decimal("0.00")

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None or amount <= Decimal("0.00"):
            raise ValidationError(_("Payment amount must be strictly greater than zero."))

        if self.invoice:
            # Allow for updating existing payment: exclude this payment's own previous amount
            other_payments = (
                self.invoice.payments.exclude(pk=self.instance.pk).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            allowable_balance = self.invoice.total - other_payments
            if amount > allowable_balance:
                raise ValidationError(
                    _(f"Payment amount (${amount:.2f}) exceeds allowable balance (${allowable_balance:.2f}).")
                )

        return amount

    def save(self, commit: bool = True):
        """
        Saves payment atomically.
        If the remaining balance reaches zero, marks the invoice as PAID.
        """
        instance = super().save(commit=False)
        if self.invoice:
            instance.invoice = self.invoice
        if self.user and not instance.recorded_by:
            instance.recorded_by = self.user

        if commit:
            with transaction.atomic():
                instance.save()
                # Re-check updated balance from the database
                self.invoice.refresh_from_db()
                if self.invoice.balance_due <= Decimal("0.00"):
                    self.invoice.status = Invoice.STATUS_PAID
                    self.invoice.save(update_fields=["status", "updated_at"])

        return instance
