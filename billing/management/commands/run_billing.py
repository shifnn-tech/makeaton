"""
billing/management/commands/run_billing.py
=========================================
Purpose:
    Management command to automate recurring billing across active subscriptions.
    Scans for active subscriptions due for billing (next_invoice_date <= today),
    executes generate_invoice() atomically per subscription, and logs a summary.

Usage:
    python manage.py run_billing
    python manage.py run_billing --dry-run
    python manage.py run_billing --subscription 12
    python manage.py run_billing --subscription SUB-202610-A1B2 --dry-run
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from subscriptions.models import Subscription
from billing.services import generate_invoice, DuplicateInvoiceError


class Command(BaseCommand):
    help = "Generates recurring invoices for active subscriptions due for billing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulates invoice generation without persisting any changes to the database.",
        )
        parser.add_argument(
            "--subscription",
            type=str,
            default=None,
            help="Optional subscription ID or subscription number to process a single subscription.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        sub_arg = options.get("subscription")
        today = timezone.localdate()

        mode_str = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(self.style.NOTICE(f"{mode_str}Starting BrightLoop recurring billing run for date: {today}"))

        # Base query for active subscriptions
        queryset = (
            Subscription.objects.filter(status=Subscription.STATUS_ACTIVE)
            .select_related("customer", "plan")
            .prefetch_related("lines__product", "lines__tax")
        )

        # Filter by specific subscription if requested
        if sub_arg:
            if sub_arg.isdigit():
                queryset = queryset.filter(id=int(sub_arg))
            else:
                queryset = queryset.filter(number=sub_arg)
        else:
            queryset = queryset.filter(next_invoice_date__lte=today)

        total_due = queryset.count()
        self.stdout.write(f"Found {total_due} active subscription(s) eligible for billing.")

        created_count = 0
        skipped_count = 0
        failed_count = 0

        for sub in queryset:
            self.stdout.write(f" -> Processing {sub.number} ({sub.customer.email})...")
            try:
                invoice = generate_invoice(sub, dry_run=dry_run, raise_on_duplicate=True)
                created_count += 1
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"    [DRY-RUN WOULD CREATE] Invoice for {sub.number}: Subtotal ${invoice.subtotal}, Total ${invoice.total}"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"    [CREATED] Invoice {invoice.number} (Total: ${invoice.total})"
                        )
                    )
            except DuplicateInvoiceError as exc:
                skipped_count += 1
                self.stdout.write(self.style.WARNING(f"    [SKIPPED - DUPLICATE] {exc}"))
            except Exception as exc:
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"    [FAILED] Error processing {sub.number}: {exc}"))

        # Structured final summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.NOTICE(f"{mode_str}Billing Run Summary:"))
        self.stdout.write(self.style.SUCCESS(f"  Created:             {created_count}"))
        self.stdout.write(self.style.WARNING(f"  Skipped (duplicate): {skipped_count}"))
        if failed_count > 0:
            self.stdout.write(self.style.ERROR(f"  Failed:              {failed_count}"))
        else:
            self.stdout.write(f"  Failed:              {failed_count}")
        self.stdout.write("=" * 50)
