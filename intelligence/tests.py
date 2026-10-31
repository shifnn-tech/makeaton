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


class RevenueLeakDetectorTests(TestCase):
    def setUp(self):
        from datetime import date, timedelta
        from django.utils import timezone
        from billing.models import Invoice, InvoiceLine, Payment

        self.client = Client()
        today = timezone.localdate()

        self.staff_user = User.objects.create_user(
            email="leak_staff@brightloop.local",
            password="SecurePassword@123",
            role="staff",
        )
        self.customer_user = User.objects.create_user(
            email="leak_customer@brightloop.local",
            password="SecurePassword@123",
            role="customer",
        )

        self.plan = Plan.objects.create(
            name="Leak Test Plan",
            price=Decimal("150.00"),
            billing_period=Plan.PERIOD_MONTHLY,
        )

        # 1. Active subscription with no invoice covering today (Check 1 target)
        self.sub_unbilled = Subscription.objects.create(
            customer=self.customer_user,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=today - timedelta(days=20),
            next_invoice_date=today + timedelta(days=10),
        )

        # 2. Active subscription with lapsed renewal (Check 2 target)
        self.sub_lapsed = Subscription.objects.create(
            customer=self.customer_user,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=today - timedelta(days=60),
            next_invoice_date=today - timedelta(days=5),
        )

        # 3. Overdue unpaid invoice (Check 3 target)
        self.inv_overdue = Invoice.objects.create(
            subscription=self.sub_unbilled,
            period_start=today - timedelta(days=50),
            period_end=today - timedelta(days=21),
            total=Decimal("150.00"),
            due_date=today - timedelta(days=7),
            status=Invoice.STATUS_CONFIRMED,
        )

        # 4. Invoice with line mismatch (Check 5 target)
        self.inv_mismatch = Invoice.objects.create(
            number="INV-LEAK-TEST-001",
            subscription=self.sub_unbilled,
            period_start=today - timedelta(days=80),
            period_end=today - timedelta(days=51),
            total=Decimal("200.00"),
            due_date=today + timedelta(days=10),
            status=Invoice.STATUS_CONFIRMED,
        )
        InvoiceLine.objects.create(
            invoice=self.inv_mismatch,
            description="Itemized Service",
            quantity=1,
            unit_price=Decimal("120.00"),
            amount=Decimal("120.00"),
        )

    def test_detect_leaks_returns_all_five_checks(self):
        from intelligence.services import detect_leaks
        leaks = detect_leaks()

        self.assertIn("total_revenue_at_risk", leaks)
        self.assertIn("total_leak_count", leaks)
        self.assertIn("checks", leaks)
        self.assertEqual(len(leaks["checks"]), 5)

        check_keys = [c["key"] for c in leaks["checks"]]
        self.assertEqual(check_keys, [
            "active_no_invoice",
            "lapsed_renewals",
            "overdue_invoices",
            "unmatched_payments",
            "line_total_mismatch",
        ])

    def test_leak_check_active_no_current_invoice(self):
        from intelligence.services import detect_leaks
        leaks = detect_leaks()
        c1 = next(c for c in leaks["checks"] if c["key"] == "active_no_invoice")

        self.assertGreaterEqual(c1["count"], 1)
        # Find self.sub_unbilled
        record = next((r for r in c1["records"] if r["id"] == self.sub_unbilled.id), None)
        self.assertIsNotNone(record)
        self.assertEqual(record["amount_at_risk"], Decimal("150.00"))
        self.assertIn("missing an invoice covering the current billing cycle", record["reason"])

    def test_leak_check_lapsed_renewals(self):
        from intelligence.services import detect_leaks
        leaks = detect_leaks()
        c2 = next(c for c in leaks["checks"] if c["key"] == "lapsed_renewals")

        self.assertGreaterEqual(c2["count"], 1)
        record = next((r for r in c2["records"] if r["id"] == self.sub_lapsed.id), None)
        self.assertIsNotNone(record)
        self.assertEqual(record["amount_at_risk"], Decimal("150.00"))
        self.assertIn("Renewal scheduled for", record["reason"])

    def test_leak_check_overdue_invoices(self):
        from intelligence.services import detect_leaks
        leaks = detect_leaks()
        c3 = next(c for c in leaks["checks"] if c["key"] == "overdue_invoices")

        self.assertGreaterEqual(c3["count"], 1)
        record = next((r for r in c3["records"] if r["id"] == self.inv_overdue.id), None)
        self.assertIsNotNone(record)
        self.assertEqual(record["amount_at_risk"], Decimal("150.00"))
        self.assertIn("Invoice deadline passed", record["reason"])

    def test_leak_check_line_total_mismatch(self):
        from intelligence.services import detect_leaks
        leaks = detect_leaks()
        c5 = next(c for c in leaks["checks"] if c["key"] == "line_total_mismatch")

        self.assertGreaterEqual(c5["count"], 1)
        record = next((r for r in c5["records"] if r["id"] == self.inv_mismatch.id), None)
        self.assertIsNotNone(record)
        # Total is 200.00, Line is 120.00 -> discrepancy is 80.00
        self.assertEqual(record["amount_at_risk"], Decimal("80.00"))

    def test_leak_detector_view_security_and_rendering(self):
        # Customers must be forbidden (HTTP 403)
        self.client.login(email="leak_customer@brightloop.local", password="SecurePassword@123")
        resp_cust = self.client.get("/intelligence/leaks/")
        self.assertEqual(resp_cust.status_code, 403)

        # Staff gets HTTP 200 with summary card and check sections
        self.client.login(email="leak_staff@brightloop.local", password="SecurePassword@123")
        resp_staff = self.client.get("/intelligence/leaks/")
        self.assertEqual(resp_staff.status_code, 200)
        self.assertContains(resp_staff, "Total Estimated Revenue at Risk")
        self.assertContains(resp_staff, "Check 1: Missing Invoices")
        self.assertContains(resp_staff, "Check 2: Unbilled Renewals")
        self.assertContains(resp_staff, "Check 3: Overdue Receivables")
        self.assertContains(resp_staff, "Check 4: Payment Discrepancies")
        self.assertContains(resp_staff, "Check 5: Integrity Discrepancies")


class WhatIfSimulatorTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            email="sim_staff@brightloop.local",
            password="SecurePassword@123",
            role="staff",
        )
        self.customer_user = User.objects.create_user(
            email="sim_customer@brightloop.local",
            password="SecurePassword@123",
            role="customer",
        )

    def test_simulate_function_math(self):
        from intelligence.services import simulate
        base = Decimal("100000.00")
        res = simulate(
            base_mrr=base,
            price_increase_pct=10.0,
            customer_growth_pct=5.0,
            churn_pct=2.0,
            months=12,
        )

        self.assertEqual(len(res["projections"]), 12)
        self.assertEqual(res["base_mrr"], Decimal("100000.00"))
        self.assertEqual(res["disclaimer"], "Simulated. Based on assumptions, not real data.")

        # ARR must strictly equal Month 12 MRR * 12
        expected_arr = res["month_12_mrr"] * Decimal("12")
        self.assertEqual(res["projected_arr"], expected_arr)

        # Cumulative revenue must equal sum of projections
        sum_mrr = sum(p["mrr"] for p in res["projections"])
        self.assertEqual(res["cumulative_revenue"], sum_mrr)

        # Delta vs baseline = cumulative - (base * 12)
        expected_delta = res["cumulative_revenue"] - (base * Decimal("12"))
        self.assertEqual(res["delta_vs_baseline"], expected_delta)
        self.assertGreater(res["delta_vs_baseline"], Decimal("0.00"))

    def test_simulate_zero_and_empty_data(self):
        from intelligence.services import simulate
        res = simulate(base_mrr=Decimal("0.00"), months=12)
        self.assertEqual(res["month_12_mrr"], Decimal("0.00"))
        self.assertEqual(res["projected_arr"], Decimal("0.00"))
        self.assertEqual(res["cumulative_revenue"], Decimal("0.00"))
        self.assertEqual(res["delta_vs_baseline"], Decimal("0.00"))

    def test_simulate_stress_churn_non_negative(self):
        from intelligence.services import simulate
        res = simulate(
            base_mrr=Decimal("50000.00"),
            price_increase_pct=-100.0,
            customer_growth_pct=0.0,
            churn_pct=50.0,
        )
        # Price decrease of 100% drops MRR to 0
        self.assertEqual(res["month_12_mrr"], Decimal("0.00"))
        # Never negative
        for p in res["projections"]:
            self.assertGreaterEqual(p["mrr"], Decimal("0.00"))

    def test_simulator_view_security_and_rendering(self):
        # Customers get 403
        self.client.login(email="sim_customer@brightloop.local", password="SecurePassword@123")
        resp_cust = self.client.get("/intelligence/simulator/")
        self.assertEqual(resp_cust.status_code, 403)

        # Staff gets 200 with sliders and disclaimer
        self.client.login(email="sim_staff@brightloop.local", password="SecurePassword@123")
        resp_staff = self.client.get("/intelligence/simulator/")
        self.assertEqual(resp_staff.status_code, 200)
        self.assertContains(resp_staff, "What-If Revenue Simulator")
        self.assertContains(resp_staff, "Simulated. Based on assumptions, not real data.")
        self.assertContains(resp_staff, "priceSlider")
        self.assertContains(resp_staff, "growthSlider")
        self.assertContains(resp_staff, "churnSlider")
        self.assertContains(resp_staff, "simulationChart")
        self.assertContains(resp_staff, "Formulas Used")

