"""
billing/admin.py
================
Purpose:
    Django admin configuration for Discounts, Invoices, Invoice Lines, and Payments.
    Includes inlines for itemized lines and payment history.
"""

from django.contrib import admin
from .models import Discount, Invoice, InvoiceLine, Payment


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 1
    fields = ("product", "description", "quantity", "unit_price", "tax_rate", "line_subtotal", "line_tax", "line_total")
    readonly_fields = ("line_subtotal", "line_tax", "line_total")


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("method", "amount", "date", "reference", "recorded_by", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "type",
        "value",
        "valid_from",
        "valid_to",
        "usage_limit",
        "times_used",
        "is_active",
        "created_at",
    )
    list_filter = ("type", "is_active", "valid_from", "valid_to")
    search_fields = ("name", "code")
    readonly_fields = ("created_at",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "subscription",
        "status",
        "period_start",
        "period_end",
        "issue_date",
        "due_date",
        "subtotal",
        "discount_total",
        "tax_total",
        "total",
        "amount_paid",
        "balance_due",
        "is_overdue",
    )
    list_filter = ("status", "due_date", "period_start", "issue_date")
    search_fields = (
        "number",
        "subscription__number",
        "subscription__customer__email",
        "subscription__customer__first_name",
        "subscription__customer__last_name",
    )
    readonly_fields = (
        "number",
        "created_at",
        "updated_at",
        "amount_paid",
        "balance_due",
        "is_overdue",
    )
    inlines = [InvoiceLineInline, PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "invoice",
        "method",
        "amount",
        "date",
        "reference",
        "recorded_by",
        "created_at",
    )
    list_filter = ("method", "date")
    search_fields = (
        "invoice__number",
        "reference",
        "invoice__subscription__customer__email",
    )
    readonly_fields = ("created_at",)
