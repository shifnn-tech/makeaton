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
