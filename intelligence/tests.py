"""
intelligence/tests.py
=====================
Purpose:
    Unit tests for the Revenue Intelligence services and dashboard views.
    Verifies:
      - MRR frequency normalisation (daily, weekly, monthly, yearly)
      - Zero-data / empty database handling (no ZeroDivisionError)
      - Role-based security (customers blocked, staff/admin allowed)
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from catalog.models import Plan
from subscriptions.models import Subscription
from intelligence.services import normalize_to_monthly, get_mrr, get_revenue_trend

User = get_user_model()


class MRRNormalizationTests(TestCase):
    def test_frequency_normalisation(self):
        # 1. Daily: price * 30
        self.assertEqual(normalize_to_monthly(Decimal("5.00"), Plan.PERIOD_DAILY), Decimal("150.00"))

        # 2. Weekly: price * 4.33 (25.00 * 4.33 = 108.25)
        self.assertEqual(normalize_to_monthly(Decimal("25.00"), Plan.PERIOD_WEEKLY), Decimal("108.25"))

        # 3. Monthly: price * 1 (99.00)
        self.assertEqual(normalize_to_monthly(Decimal("99.00"), Plan.PERIOD_MONTHLY), Decimal("99.00"))

        # 4. Yearly: price / 12 (1200.00 / 12 = 100.00)
        self.assertEqual(normalize_to_monthly(Decimal("1200.00"), Plan.PERIOD_YEARLY), Decimal("100.00"))

    def test_zero_and_negative_prices(self):
        self.assertEqual(normalize_to_monthly(Decimal("0.00"), Plan.PERIOD_MONTHLY), Decimal("0.00"))
        self.assertEqual(normalize_to_monthly(None, Plan.PERIOD_MONTHLY), Decimal("0.00"))


class EmptyDataHandlingTests(TestCase):
    def test_get_mrr_empty(self):
        res = get_mrr()
        self.assertEqual(res["mrr"], Decimal("0.00"))
        self.assertEqual(res["arr"], Decimal("0.00"))
        self.assertEqual(res["active_count"], 0)

    def test_get_revenue_trend_empty(self):
        res = get_revenue_trend(months=6)
        self.assertEqual(res["trend"], [])
        self.assertEqual(res["labels"], [])
        self.assertEqual(res["data"], [])
        self.assertEqual(res["latest_revenue"], Decimal("0.00"))
        self.assertEqual(res["latest_mom_growth"], 0.0)


class RevenueDashboardViewSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            email="intel_admin@brightloop.local",
            password="SecurePassword@123",
            role=User.ROLE_ADMIN,
        )
        self.staff_user = User.objects.create_user(
            email="intel_staff@brightloop.local",
            password="SecurePassword@123",
            role=User.ROLE_STAFF,
        )
        self.customer_user = User.objects.create_user(
            email="intel_customer@brightloop.local",
            password="SecurePassword@123",
            role=User.ROLE_CUSTOMER,
        )

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get("/intelligence/")
        self.assertEqual(resp.status_code, 302)

    def test_customer_access_forbidden(self):
        self.client.login(email="intel_customer@brightloop.local", password="SecurePassword@123")
        resp = self.client.get("/intelligence/")
        self.assertEqual(resp.status_code, 403)

    def test_staff_access_permitted(self):
        self.client.login(email="intel_staff@brightloop.local", password="SecurePassword@123")
        resp = self.client.get("/intelligence/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_access_permitted(self):
        self.client.login(email="intel_admin@brightloop.local", password="SecurePassword@123")
        resp = self.client.get("/intelligence/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Revenue Intelligence")


class ForecastAndHealthScoreTests(TestCase):
    def setUp(self):
        from datetime import date, timedelta
        from billing.models import Invoice, Payment

        self.client = Client()
        self.staff_user = User.objects.create_user(
            email="staff_tester@brightloop.local",
            password="SecurePassword@123",
            role=User.ROLE_STAFF,
        )
        self.plan = Plan.objects.create(name="Pro Plan", price=Decimal("100.00"), billing_period=Plan.PERIOD_MONTHLY)
        self.customer = User.objects.create_user(
            email="subscriber1@brightloop.local",
            password="SecurePassword@123",
            role=User.ROLE_CUSTOMER,
        )

        today = date.today()
        # Create subscription 1 (Healthy)
        self.sub_healthy = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=today - timedelta(days=200),
        )
        inv1 = Invoice.objects.create(
            subscription=self.sub_healthy,
            period_start=today - timedelta(days=60),
            period_end=today - timedelta(days=30),
            total=Decimal("100.00"),
            due_date=today - timedelta(days=45),
            status=Invoice.STATUS_PAID,
        )
        Payment.objects.create(
            invoice=inv1,
            method=Payment.METHOD_CREDIT_CARD,
            amount=Decimal("100.00"),
            date=today - timedelta(days=50),
        )

        # Create subscription 2 (Unhealthy with 2 overdue invoices)
        self.sub_unhealthy = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=today - timedelta(days=40),
        )
        Invoice.objects.create(
            subscription=self.sub_unhealthy,
            period_start=today - timedelta(days=30),
            period_end=today - timedelta(days=1),
            total=Decimal("100.00"),
            due_date=today - timedelta(days=10),
            status=Invoice.STATUS_CONFIRMED,
        )
        Invoice.objects.create(
            subscription=self.sub_unhealthy,
            period_start=today - timedelta(days=60),
            period_end=today - timedelta(days=31),
            total=Decimal("100.00"),
            due_date=today - timedelta(days=40),
            status=Invoice.STATUS_CONFIRMED,
        )

    def test_forecast_revenue_structure(self):
        from intelligence.services import forecast_revenue
        forecast_res = forecast_revenue(months_ahead=3)
        self.assertEqual(len(forecast_res["forecast"]), 3)
        self.assertTrue(forecast_res["total_projected"] >= Decimal("0.00"))
        self.assertIn("Assumptions", forecast_res["assumptions"])

    def test_subscription_health_scores_and_risk(self):
        from intelligence.services import get_subscription_health_scores
        health_res = get_subscription_health_scores()

        # Both subscriptions are present
        self.assertGreaterEqual(health_res["total_count"], 2)

        # Find healthy and unhealthy in result list
        healthy_item = next(s for s in health_res["subscriptions"] if s["id"] == self.sub_healthy.id)
        unhealthy_item = next(s for s in health_res["subscriptions"] if s["id"] == self.sub_unhealthy.id)

        # Healthy subscriber should have higher score and Low risk
        self.assertGreater(healthy_item["health_score"], 70)
        self.assertEqual(healthy_item["risk_label"], "Low")

        # Unhealthy subscriber with 2 overdue invoices must be High risk
        self.assertEqual(unhealthy_item["risk_label"], "High")

        # Result list must be sorted with High risk at the top
        self.assertEqual(health_res["subscriptions"][0]["risk_label"], "High")

    def test_forecast_view_http200(self):
        self.client.login(email="staff_tester@brightloop.local", password="SecurePassword@123")
        resp = self.client.get("/intelligence/forecast/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "3-Month Revenue Forecast")
        self.assertContains(resp, "Subscriber Health Score")

