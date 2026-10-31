"""
portal/tests.py
===============
Test suite for the BrightLoop unified portal:
  - Role-based landing redirection (admin, staff, customer)
  - Admin dashboard metrics and access controls
  - Staff dashboard task queues and access controls
  - Customer dashboard isolation and self-service metrics
  - Global search view with role-based result scoping
  - Billing calendar and 30-day renewal calculation
  - Staff-only customer list and customer profile views
"""

import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.models import Plan
from subscriptions.models import Subscription
from billing.models import Invoice, Payment


class PortalViewsTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Create test users for each role
        self.admin_user = User.objects.create_user(
            email="admin@test.com",
            password="AdminPassword123!",
            role=User.ROLE_ADMIN,
            is_staff=True,
        )
        self.staff_user = User.objects.create_user(
            email="staff@test.com",
            password="StaffPassword123!",
            role=User.ROLE_STAFF,
            is_staff=True,
        )
        self.customer1 = User.objects.create_user(
            email="cust1@test.com",
            password="CustomerPassword123!",
            role=User.ROLE_CUSTOMER,
            first_name="Alice",
            last_name="Smith",
        )
        self.customer2 = User.objects.create_user(
            email="cust2@test.com",
            password="CustomerPassword123!",
            role=User.ROLE_CUSTOMER,
            first_name="Bob",
            last_name="Jones",
        )

        # Create test plan
        self.plan = Plan.objects.create(
            name="Pro Plan",
            price=Decimal("100.00"),
            billing_period=Plan.PERIOD_MONTHLY,
        )

        today = timezone.localdate()

        # Customer 1 subscription and invoice
        self.sub1 = Subscription.objects.create(
            number="SUB-0001",
            customer=self.customer1,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=today,
            next_invoice_date=today + datetime.timedelta(days=5),
        )
        self.inv1 = Invoice.objects.create(
            number="INV-0001",
            subscription=self.sub1,
            status=Invoice.STATUS_CONFIRMED,
            period_start=today,
            period_end=today + datetime.timedelta(days=30),
            due_date=today + datetime.timedelta(days=7),
            total=Decimal("100.00"),
        )

        # Customer 2 subscription and overdue invoice
        self.sub2 = Subscription.objects.create(
            number="SUB-0002",
            customer=self.customer2,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=today - datetime.timedelta(days=40),
            next_invoice_date=today + datetime.timedelta(days=15),
        )
        self.inv2 = Invoice.objects.create(
            number="INV-0002",
            subscription=self.sub2,
            status=Invoice.STATUS_CONFIRMED,
            period_start=today - datetime.timedelta(days=35),
            period_end=today - datetime.timedelta(days=5),
            due_date=today - datetime.timedelta(days=5),
            total=Decimal("100.00"),
        )

    # 1. Landing View Tests
    def test_landing_redirects_by_role(self):
        # Admin landing
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse("portal:landing"))
        self.assertRedirects(res, reverse("portal:admin_dashboard"))

        # Staff landing
        self.client.force_login(self.staff_user)
        res = self.client.get(reverse("portal:landing"))
        self.assertRedirects(res, reverse("portal:staff_dashboard"))

        # Customer landing
        self.client.force_login(self.customer1)
        res = self.client.get(reverse("portal:landing"))
        self.assertRedirects(res, reverse("portal:customer_dashboard"))

    # 2. Admin Dashboard Tests
    def test_admin_dashboard_access_and_metrics(self):
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse("portal:admin_dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "portal/admin_dashboard.html")
        self.assertEqual(res.context["active_subscriptions_count"], 2)
        self.assertEqual(res.context["unpaid_invoices_count"], 2)

        # Customers should get 403 forbidden
        self.client.force_login(self.customer1)
        res = self.client.get(reverse("portal:admin_dashboard"))
        self.assertEqual(res.status_code, 403)

    # 3. Staff Dashboard Tests
    def test_staff_dashboard_access(self):
        self.client.force_login(self.staff_user)
        res = self.client.get(reverse("portal:staff_dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "portal/staff_dashboard.html")
        self.assertIn("invoices_due_soon", res.context)
        self.assertIn("overdue_invoices", res.context)

        # Customer should get 403 forbidden
        self.client.force_login(self.customer1)
        res = self.client.get(reverse("portal:staff_dashboard"))
        self.assertEqual(res.status_code, 403)

    # 4. Customer Dashboard Tests
    def test_customer_dashboard_isolation(self):
        self.client.force_login(self.customer1)
        res = self.client.get(reverse("portal:customer_dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "portal/customer_dashboard.html")
        # Customer 1 should only see their own active subscription
        self.assertEqual(len(res.context["active_subscriptions"]), 1)
        self.assertEqual(res.context["active_subscriptions"][0].number, "SUB-0001")
        # Customer 1 should only see their own unpaid invoice
        self.assertEqual(len(res.context["unpaid_invoices"]), 1)
        self.assertEqual(res.context["unpaid_invoices"][0].number, "INV-0001")

    # 5. Global Search Tests
    def test_global_search_role_scoping(self):
        # Staff can find customer by email
        self.client.force_login(self.staff_user)
        res = self.client.get(reverse("portal:search") + "?q=cust1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context["customers"]), 1)

        # Customer searching "SUB-0002" (belongs to customer2) should find 0 results
        self.client.force_login(self.customer1)
        res = self.client.get(reverse("portal:search") + "?q=SUB-0002")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context["subscriptions"]), 0)

        # Customer searching "SUB-0001" (their own) finds 1 result
        res = self.client.get(reverse("portal:search") + "?q=SUB-0001")
        self.assertEqual(len(res.context["subscriptions"]), 1)

    # 6. Billing Calendar Tests
    def test_billing_calendar(self):
        self.client.force_login(self.staff_user)
        res = self.client.get(reverse("portal:calendar"))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "portal/billing_calendar.html")
        self.assertEqual(len(res.context["weeks"]), 4)
        self.assertEqual(res.context["grand_total_subs"], 2)

    # 7. Customer List and Detail Tests
    def test_customer_list_and_detail(self):
        self.client.force_login(self.staff_user)
        res = self.client.get(reverse("portal:customer_list"))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "portal/customer_list.html")
        self.assertEqual(res.context["total_customers"], 2)

        res_detail = self.client.get(reverse("portal:customer_detail", args=[self.customer1.id]))
        self.assertEqual(res_detail.status_code, 200)
        self.assertTemplateUsed(res_detail, "portal/customer_detail.html")
        self.assertEqual(res_detail.context["customer"].email, "cust1@test.com")
