"""
subscriptions/tests.py
======================
Purpose:
    Unit tests for Subscription status transitions, finite state machine,
    and subscribing to catalog plans.
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from catalog.models import Plan
from subscriptions.models import Subscription

User = get_user_model()


class SubscriptionStateMachineTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(email="subtest@example.com", password="Password@123")
        self.plan = Plan.objects.create(name="Test Plan", price=Decimal("10.00"), billing_period=Plan.PERIOD_MONTHLY)
        self.sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.STATUS_DRAFT,
        )

    def test_valid_transitions(self):
        # Draft -> Quotation is allowed
        self.sub.change_status(Subscription.STATUS_QUOTATION)
        self.assertEqual(self.sub.status, Subscription.STATUS_QUOTATION)

        # Quotation -> Confirmed is allowed
        self.sub.change_status(Subscription.STATUS_CONFIRMED)
        self.assertEqual(self.sub.status, Subscription.STATUS_CONFIRMED)

        # Confirmed -> Active is allowed
        self.sub.change_status(Subscription.STATUS_ACTIVE)
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)

        # Active -> Closed is allowed
        self.sub.change_status(Subscription.STATUS_CLOSED)
        self.assertEqual(self.sub.status, Subscription.STATUS_CLOSED)

    def test_invalid_transitions(self):
        # Draft cannot jump directly to Active
        with self.assertRaises(ValidationError):
            self.sub.change_status(Subscription.STATUS_ACTIVE)

        # Closed cannot transition anywhere (terminal state)
        self.sub.status = Subscription.STATUS_CLOSED
        self.sub.save()
        with self.assertRaises(ValidationError):
            self.sub.change_status(Subscription.STATUS_ACTIVE)


class SubscriptionViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.customer = User.objects.create_user(
            email="subscriber@example.com",
            password="SecurePassword@123",
            role=User.ROLE_CUSTOMER,
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="SecurePassword@123",
        )
        self.plan = Plan.objects.create(
            name="Starter Pro",
            price=Decimal("49.00"),
            billing_period=Plan.PERIOD_MONTHLY,
        )

    def test_customer_can_subscribe_to_plan(self):
        self.client.login(email="subscriber@example.com", password="SecurePassword@123")
        response = self.client.post(reverse("subscriptions:subscribe", args=[self.plan.id]))
        self.assertEqual(response.status_code, 302)

        # Verify subscription was created and is Active
        subscription = Subscription.objects.filter(customer=self.customer, plan=self.plan).first()
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.status, Subscription.STATUS_ACTIVE)

        # Verify an invoice was generated
        self.assertEqual(subscription.invoices.count(), 1)
        invoice = subscription.invoices.first()
        self.assertGreater(invoice.total, Decimal("0.00"))

    def test_staff_can_transition_subscription_status(self):
        self.client.login(email="admin@example.com", password="SecurePassword@123")
        sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.STATUS_DRAFT,
        )
        url = reverse("subscriptions:change_status", args=[sub.id, Subscription.STATUS_QUOTATION])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_QUOTATION)
