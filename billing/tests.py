"""
billing/tests.py
================
Purpose:
    Unit tests for Invoice unique constraints, status transitions, dynamic properties,
    Payment validation, recurring invoice generation, and paying invoices.
"""

from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from catalog.models import Plan, Product
from subscriptions.models import Subscription, SubscriptionLine
from billing.models import Invoice, Payment
from billing.services import generate_invoice

User = get_user_model()


class BillingModelTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(email="billingtest@example.com", password="Password@123")
        self.plan = Plan.objects.create(name="Pro Plan", price=Decimal("100.00"), billing_period=Plan.PERIOD_MONTHLY)
        self.sub = Subscription.objects.create(customer=self.customer, plan=self.plan, status=Subscription.STATUS_ACTIVE)
        self.today = date.today()

    def test_unique_period_start_constraint(self):
        Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            total=Decimal("100.00"),
            due_date=self.today + timedelta(days=14),
        )

        with self.assertRaises(IntegrityError):
            Invoice.objects.create(
                subscription=self.sub,
                period_start=self.today,
                period_end=self.today + timedelta(days=30),
                total=Decimal("100.00"),
                due_date=self.today + timedelta(days=14),
            )

    def test_payment_amount_validation(self):
        inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            total=Decimal("100.00"),
            due_date=self.today + timedelta(days=14),
            status=Invoice.STATUS_CONFIRMED,
        )

        # Payment <= 0 must fail
        with self.assertRaises(ValidationError):
            p = Payment(invoice=inv, amount=Decimal("0.00"))
            p.clean()

        # Payment > remaining balance must fail
        with self.assertRaises(ValidationError):
            p = Payment(invoice=inv, amount=Decimal("150.00"))
            p.clean()

        # Exact payment succeeds and marks invoice as Paid
        p = Payment.objects.create(invoice=inv, amount=Decimal("100.00"))
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.STATUS_PAID)
        self.assertEqual(inv.balance_due, Decimal("0.00"))


class BillingServiceAndPaymentViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.customer = User.objects.create_user(
            email="custpay@example.com",
            password="SecurePassword@123",
            role=User.ROLE_CUSTOMER,
        )
        self.plan = Plan.objects.create(
            name="Cloud Gold",
            price=Decimal("120.00"),
            billing_period=Plan.PERIOD_MONTHLY,
        )
        self.sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            next_invoice_date=date.today(),
        )

    def test_generate_invoice_service(self):
        invoice = generate_invoice(self.sub)
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.subscription, self.sub)
        self.assertGreater(invoice.total, Decimal("0.00"))
        self.assertEqual(invoice.status, Invoice.STATUS_CONFIRMED)

        # Idempotency check: running with the same period_start returns existing invoice
        inv2 = generate_invoice(self.sub, period_start=invoice.period_start)
        self.assertEqual(inv2.id, invoice.id)

    def test_customer_can_pay_invoice_via_portal(self):
        self.client.login(email="custpay@example.com", password="SecurePassword@123")
        invoice = generate_invoice(self.sub)

        # Post payment
        response = self.client.post(reverse("billing:pay", args=[invoice.id]))
        self.assertEqual(response.status_code, 302)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.STATUS_PAID)
        self.assertEqual(invoice.balance_due, Decimal("0.00"))
        self.assertEqual(invoice.payments.count(), 1)
