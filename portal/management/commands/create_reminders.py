"""
portal/management/commands/create_reminders.py
==============================================
Management command to generate automated notification reminders for:
  1. Invoices due soon (due within the next 7 days and unpaid)
  2. Invoices overdue (due_date in the past and unpaid)

Ensures zero duplicate notifications by verifying whether a reminder for
the specific invoice link and notification category already exists.
"""

import datetime
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice
from portal.models import Notification


class Command(BaseCommand):
    help = "Generates 'invoice due soon' and 'invoice overdue' notifications for customers without creating duplicates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Number of days in advance to consider an invoice 'due soon' (default: 7).",
        )

    def handle(self, *args, **options):
        today = timezone.localdate()
        days_ahead = options.get("days", 7)
        due_soon_cutoff = today + datetime.timedelta(days=days_ahead)

        due_soon_created = 0
        overdue_created = 0

        # ----------------------------------------------------------------------
        # 1. Invoices Due Soon
        # ----------------------------------------------------------------------
        # Invoices due between today and +days_ahead that are not yet paid
        due_soon_invoices = (
            Invoice.objects
            .select_related("subscription__customer")
            .filter(
                due_date__gte=today,
                due_date__lte=due_soon_cutoff,
            )
            .exclude(status__in=[Invoice.STATUS_PAID, Invoice.STATUS_CANCELLED])
        )

        for inv in due_soon_invoices:
            customer = inv.subscription.customer
            inv_link = reverse("billing:detail", args=[inv.id])

            # Duplicate prevention check: do not recreate if reminder already exists
            already_notified = Notification.objects.filter(
                user=customer,
                link=inv_link,
                message__icontains="due soon",
            ).exists()

            if not already_notified:
                Notification.objects.create(
                    user=customer,
                    message=f"Invoice #{inv.number} of ${inv.total:.2f} is due soon on {inv.due_date.strftime('%b %d, %Y')}.",
                    link=inv_link,
                    is_read=False,
                )
                due_soon_created += 1

        # ----------------------------------------------------------------------
        # 2. Overdue Invoices
        # ----------------------------------------------------------------------
        # Invoices whose due_date has passed and are still not paid
        overdue_invoices = (
            Invoice.objects
            .select_related("subscription__customer")
            .filter(due_date__lt=today)
            .exclude(status__in=[Invoice.STATUS_PAID, Invoice.STATUS_CANCELLED])
        )

        for inv in overdue_invoices:
            customer = inv.subscription.customer
            inv_link = reverse("billing:detail", args=[inv.id])

            # Duplicate prevention check: do not recreate if overdue reminder already exists
            already_notified = Notification.objects.filter(
                user=customer,
                link=inv_link,
                message__icontains="overdue",
            ).exists()

            if not already_notified:
                Notification.objects.create(
                    user=customer,
                    message=f"Invoice #{inv.number} of ${inv.total:.2f} is overdue (was due on {inv.due_date.strftime('%b %d, %Y')}).",
                    link=inv_link,
                    is_read=False,
                )
                overdue_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Reminder check complete: {due_soon_created} 'due soon' and {overdue_created} 'overdue' notification(s) created."
            )
        )

