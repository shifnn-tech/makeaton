"""
billing/tests.py
================
Purpose:
    Unit tests for billing models, validations, dynamic financial calculations,
    Invoice unique constraints, status transitions, Payment validations,
    invoice generation service, customer portal payments, and management commands.
"""

from io import StringIO
from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.contrib.auth import get_user_model
from catalog.models import Plan, Product, Tax
from subscriptions.models import Subscription, SubscriptionLine
from billing.models import Discount, Invoice, InvoiceLine, Payment
from billing.services import generate_invoice, DuplicateInvoiceError

User = get_user_model()


class BillingModelTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            email="staff_billing@example.local",
            password="Password@123",
            role=User.ROLE_STAFF,
        )
        self.customer = User.objects.create_user(
            email="billingtest@example.com",
            password="Password@123",
            role=User.ROLE_CUSTOMER,
        )
        self.plan = Plan.objects.create(
            name="Pro Monthly",
            price=Decimal("100.00"),
            billing_period=Plan.PERIOD_MONTHLY,
        )
        self.product = Product.objects.create(
            name="Cloud Storage 100GB",
            sales_price=Decimal("50.00"),
        )
        self.sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
        )
        self.today = date.today()

    def test_unique_period_start_constraint(self):
        """Verifies duplicate invoice creation for the same subscription and period_start is blocked."""
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

    def test_invoice_auto_number_and_properties(self):
        """Verifies invoice number auto-generation, subtotal, balance_due, and aliases."""
        inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            subtotal=Decimal("100.00"),
            discount_total=Decimal("10.00"),
            tax_total=Decimal("16.20"),
            total=Decimal("106.20"),
            due_date=self.today + timedelta(days=14),
        )

        self.assertTrue(inv.number.startswith("INV-"))
        self.assertEqual(inv.invoice_number, inv.number)
        self.assertEqual(inv.discount_amount, Decimal("10.00"))
        self.assertEqual(inv.tax_amount, Decimal("16.20"))
        self.assertEqual(inv.amount_paid, Decimal("0.00"))
        self.assertEqual(inv.balance_due, Decimal("106.20"))

    def test_invoice_line_computed_properties(self):
        """Verifies InvoiceLine computed properties: subtotal, tax, and total."""
        inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            total=Decimal("118.00"),
            due_date=self.today + timedelta(days=14),
        )

        line = InvoiceLine.objects.create(
            invoice=inv,
            product=self.product,
            description="Cloud Storage",
            quantity=2,
            unit_price=Decimal("50.00"),
            tax_rate=Decimal("18.00"),
        )

        self.assertEqual(line.line_subtotal, Decimal("100.00"))
        self.assertEqual(line.line_tax, Decimal("18.00"))
        self.assertEqual(line.line_total, Decimal("118.00"))
        self.assertEqual(line.amount, Decimal("100.00"))

    def test_payment_validation_zero_and_negative(self):
        """Verifies zero or negative payments are blocked by validation and save."""
        inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            total=Decimal("100.00"),
            due_date=self.today + timedelta(days=14),
        )

        with self.assertRaises(ValidationError):
            p_zero = Payment(invoice=inv, amount=Decimal("0.00"), method=Payment.METHOD_CARD)
            p_zero.clean()

        with self.assertRaises(ValidationError):
            p_zero = Payment(invoice=inv, amount=Decimal("0.00"), method=Payment.METHOD_CARD)
            p_zero.save()

        with self.assertRaises(ValidationError):
            p_neg = Payment(invoice=inv, amount=Decimal("-10.00"), method=Payment.METHOD_CARD)
            p_neg.clean()

        with self.assertRaises(ValidationError):
            p_neg = Payment(invoice=inv, amount=Decimal("-10.00"), method=Payment.METHOD_CARD)
            p_neg.save()

    def test_payment_validation_overpayment(self):
        """Verifies payments exceeding balance due are blocked."""
        inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            total=Decimal("100.00"),
            due_date=self.today + timedelta(days=14),
        )

        with self.assertRaises(ValidationError):
            p_excess = Payment(invoice=inv, amount=Decimal("150.00"), method=Payment.METHOD_CARD)
            p_excess.clean()

        with self.assertRaises(ValidationError):
            p_excess = Payment(invoice=inv, amount=Decimal("150.00"), method=Payment.METHOD_CARD)
            p_excess.save()

    def test_payment_editing_excludes_self_from_balance(self):
        """Verifies editing an existing payment correctly excludes itself when checking balance due."""
        inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            total=Decimal("100.00"),
            due_date=self.today + timedelta(days=14),
        )

        p1 = Payment.objects.create(
            invoice=inv,
            amount=Decimal("40.00"),
            method=Payment.METHOD_CARD,
            recorded_by=self.staff_user,
        )

        p1.amount = Decimal("80.00")
        p1.clean()
        p1.save()

        self.assertEqual(inv.amount_paid, Decimal("80.00"))
        self.assertEqual(inv.balance_due, Decimal("20.00"))

        p1.amount = Decimal("105.00")
        with self.assertRaises(ValidationError):
            p1.clean()

    def test_partial_payment_then_full_payment_marks_invoice_paid(self):
        """Verifies partial payment reduces balance, and full settlement marks CONFIRMED invoice as PAID."""
        inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            status=Invoice.STATUS_CONFIRMED,
            total=Decimal("100.00"),
            due_date=self.today + timedelta(days=14),
        )

        Payment.objects.create(invoice=inv, amount=Decimal("40.00"), method=Payment.METHOD_CARD)
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal("40.00"))
        self.assertEqual(inv.balance_due, Decimal("60.00"))
        self.assertEqual(inv.status, Invoice.STATUS_CONFIRMED)

        Payment.objects.create(invoice=inv, amount=Decimal("60.00"), method=Payment.METHOD_UPI)
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal("100.00"))
        self.assertEqual(inv.balance_due, Decimal("0.00"))
        self.assertEqual(inv.status, Invoice.STATUS_PAID)

    def test_payment_amount_validation(self):
        """Verifies payment clean validation on zero and overpayment, and marks confirmed invoice paid."""
        inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            total=Decimal("100.00"),
            due_date=self.today + timedelta(days=14),
            status=Invoice.STATUS_CONFIRMED,
        )

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

    def test_status_transitions_confirm_and_mark_paid(self):
        """Verifies confirm() and mark_paid() enforce state transitions and raise ValidationError on illegal moves."""
        inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=self.today + timedelta(days=30),
            status=Invoice.STATUS_DRAFT,
            total=Decimal("100.00"),
            due_date=self.today + timedelta(days=14),
        )

        # Illegal: cannot jump DRAFT -> PAID
        with self.assertRaises(ValidationError):
            inv.mark_paid()

        # Valid: DRAFT -> CONFIRMED
        inv.confirm()
        self.assertEqual(inv.status, Invoice.STATUS_CONFIRMED)

        # Illegal: cannot re-confirm CONFIRMED
        with self.assertRaises(ValidationError):
            inv.confirm()

        # Valid: CONFIRMED -> PAID
        inv.mark_paid()
        self.assertEqual(inv.status, Invoice.STATUS_PAID)

        # Illegal: cannot move from terminal PAID state
        with self.assertRaises(ValidationError):
            inv.confirm()

    def test_overdue_and_outstanding_queries(self):
        """Verifies overdue() and outstanding() manager querysets return expected invoices."""
        past_date = self.today - timedelta(days=20)
        future_date = self.today + timedelta(days=20)

        inv_overdue = Invoice.objects.create(
            subscription=self.sub,
            period_start=past_date - timedelta(days=30),
            period_end=past_date,
            status=Invoice.STATUS_CONFIRMED,
            total=Decimal("100.00"),
            due_date=past_date,
        )

        inv_paid_past = Invoice.objects.create(
            subscription=self.sub,
            period_start=past_date - timedelta(days=60),
            period_end=past_date - timedelta(days=30),
            status=Invoice.STATUS_PAID,
            total=Decimal("100.00"),
            due_date=past_date,
        )
        Payment.objects.create(invoice=inv_paid_past, amount=Decimal("100.00"), method=Payment.METHOD_CASH)

        inv_future = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.today,
            period_end=future_date,
            status=Invoice.STATUS_CONFIRMED,
            total=Decimal("200.00"),
            due_date=future_date,
        )

        inv_draft = Invoice.objects.create(
            subscription=self.sub,
            period_start=past_date - timedelta(days=90),
            period_end=past_date - timedelta(days=60),
            status=Invoice.STATUS_DRAFT,
            total=Decimal("50.00"),
            due_date=past_date,
        )

        overdue_invoices = list(Invoice.objects.overdue())
        self.assertIn(inv_overdue, overdue_invoices)
        self.assertIn(inv_draft, overdue_invoices)
        self.assertNotIn(inv_paid_past, overdue_invoices)
        self.assertNotIn(inv_future, overdue_invoices)

        outstanding_invoices = list(Invoice.objects.outstanding())
        self.assertIn(inv_overdue, outstanding_invoices)
        self.assertIn(inv_future, outstanding_invoices)
        self.assertNotIn(inv_paid_past, outstanding_invoices)
        self.assertNotIn(inv_draft, outstanding_invoices)

    def test_discount_validation_and_calculation(self):
        """Verifies Discount model validations and calculate() logic."""
        disc_invalid_pct = Discount(name="Over 100", code="ERR101", type=Discount.TYPE_PERCENTAGE, value=Decimal("105.00"))
        with self.assertRaises(ValidationError):
            disc_invalid_pct.clean()

        disc_invalid_fixed = Discount(name="Zero Fixed", code="ERR0", type=Discount.TYPE_FIXED, value=Decimal("0.00"))
        with self.assertRaises(ValidationError):
            disc_invalid_fixed.clean()

        disc_invalid_dates = Discount(
            name="Date Error",
            code="ERRDATE",
            type=Discount.TYPE_FIXED,
            value=Decimal("10.00"),
            valid_from=self.today,
            valid_to=self.today - timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            disc_invalid_dates.clean()

        disc_pct = Discount.objects.create(
            name="20 Percent Off",
            code="SAVE20",
            type=Discount.TYPE_PERCENTAGE,
            value=Decimal("20.00"),
            is_active=True,
        )
        self.assertEqual(disc_pct.calculate(Decimal("100.00")), Decimal("20.00"))

        disc_fixed = Discount.objects.create(
            name="25 Off",
            code="SAVE25",
            type=Discount.TYPE_FIXED,
            value=Decimal("25.00"),
            is_active=True,
        )
        self.assertEqual(disc_fixed.calculate(Decimal("100.00")), Decimal("25.00"))
        self.assertEqual(disc_fixed.calculate(Decimal("15.00")), Decimal("15.00"))

        disc_fixed.is_active = False
        disc_fixed.save()
        self.assertEqual(disc_fixed.calculate(Decimal("100.00")), Decimal("0.00"))

        disc_pct.usage_limit = 1
        disc_pct.times_used = 1
        disc_pct.save()
        self.assertEqual(disc_pct.calculate(Decimal("100.00")), Decimal("0.00"))


class BillingServiceTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email="service_customer@brightloop.local",
            password="Password@123",
            role=User.ROLE_CUSTOMER,
        )
        self.tax_18 = Tax.objects.create(name="GST 18%", rate=Decimal("18.00"))
        self.tax_5 = Tax.objects.create(name="VAT 5%", rate=Decimal("5.00"))

        self.plan = Plan.objects.create(
            name="Pro Recurring",
            price=Decimal("100.00"),
            billing_period=Plan.PERIOD_MONTHLY,
        )
        self.prod_api = Product.objects.create(
            name="API Access",
            sales_price=Decimal("60.00"),
        )
        self.prod_support = Product.objects.create(
            name="Priority Support",
            sales_price=Decimal("40.00"),
        )

        self.sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=date.today(),
            next_invoice_date=date.today(),
            payment_terms="Net 15",
        )
        SubscriptionLine.objects.create(
            subscription=self.sub,
            product=self.prod_api,
            quantity=1,
            unit_price=Decimal("60.00"),
            tax=self.tax_18,
            amount=Decimal("60.00"),
        )
        SubscriptionLine.objects.create(
            subscription=self.sub,
            product=self.prod_support,
            quantity=1,
            unit_price=Decimal("40.00"),
            tax=self.tax_5,
            amount=Decimal("40.00"),
        )

    def test_generate_invoice_persists_lines_and_advances_date(self):
        """Verifies generate_invoice() creates invoice, lines, and advances next_invoice_date."""
        start = date.today()
        inv = generate_invoice(self.sub, period_start=start)

        self.assertIsNotNone(inv.id)
        self.assertEqual(inv.subscription, self.sub)
        self.assertEqual(inv.subtotal, Decimal("100.00"))
        # Line 1: 60 * 18% = 10.80
        # Line 2: 40 * 5% = 2.00
        # tax_total = 12.80
        self.assertEqual(inv.tax_total, Decimal("12.80"))
        self.assertEqual(inv.total, Decimal("112.80"))
        self.assertEqual(inv.lines.count(), 2)

        # Check advanced next_invoice_date
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.next_invoice_date, inv.period_end)

    def test_generate_invoice_duplicate_raises_error(self):
        """Verifies duplicate invoice creation for the same period raises DuplicateInvoiceError."""
        start = date.today()
        generate_invoice(self.sub, period_start=start)

        with self.assertRaises(DuplicateInvoiceError):
            generate_invoice(self.sub, period_start=start, raise_on_duplicate=True)

    def test_generate_invoice_with_discount_applied_before_tax(self):
        """
        Verifies discount is applied before tax and allocated proportionally across lines:
          - Subtotal: $100 ($60 @ 18% tax, $40 @ 5% tax)
          - Discount: $20 (allocated: $12 to Line 1, $8 to Line 2)
          - Line 1 taxable: $48 * 18% = $8.64
          - Line 2 taxable: $32 * 5% = $1.60
          - Tax total: $10.24
          - Total: $100 - $20 + $10.24 = $90.24
        """
        disc = Discount.objects.create(
            name="20 Dollar Voucher",
            code="VOUCHER20",
            type=Discount.TYPE_FIXED,
            value=Decimal("20.00"),
            is_active=True,
        )

        inv = generate_invoice(self.sub, period_start=date.today(), discount=disc)
        self.assertEqual(inv.subtotal, Decimal("100.00"))
        self.assertEqual(inv.discount_total, Decimal("20.00"))
        self.assertEqual(inv.tax_total, Decimal("10.24"))
        self.assertEqual(inv.total, Decimal("90.24"))

        # Discount times_used incremented
        disc.refresh_from_db()
        self.assertEqual(disc.times_used, 1)

    def test_generate_invoice_dry_run_saves_nothing(self):
        """Verifies dry_run=True computes complete invoice without touching the database."""
        disc = Discount.objects.create(
            name="10 Percent Voucher",
            code="VOUCHER10",
            type=Discount.TYPE_PERCENTAGE,
            value=Decimal("10.00"),
            is_active=True,
        )
        orig_next_date = self.sub.next_invoice_date

        inv = generate_invoice(self.sub, period_start=date.today(), dry_run=True, discount=disc)

        # In-memory calculations are accurate
        self.assertIsNone(inv.id)
        self.assertTrue(inv.number.startswith("INV-DRYRUN-"))
        self.assertEqual(inv.subtotal, Decimal("100.00"))
        self.assertEqual(inv.discount_total, Decimal("10.00"))
        self.assertEqual(len(inv._dry_run_lines), 2)

        # Database state remains completely untouched
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(InvoiceLine.objects.count(), 0)

        disc.refresh_from_db()
        self.assertEqual(disc.times_used, 0)

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.next_invoice_date, orig_next_date)


class BillingCommandTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email="cmd_customer@brightloop.local",
            password="Password@123",
            role=User.ROLE_CUSTOMER,
        )
        self.plan = Plan.objects.create(
            name="Basic Monthly",
            price=Decimal("50.00"),
            billing_period=Plan.PERIOD_MONTHLY,
        )
        self.today = date.today()

        # Due subscription
        self.sub_due = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=self.today - timedelta(days=35),
            next_invoice_date=self.today - timedelta(days=5),
        )

        # Future subscription (not due)
        self.sub_future = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=self.today,
            next_invoice_date=self.today + timedelta(days=20),
        )

    def test_run_billing_dry_run_flag(self):
        """Verifies run_billing --dry-run prints plan without creating database records."""
        out = StringIO()
        call_command("run_billing", "--dry-run", stdout=out)
        output = out.getvalue()

        self.assertIn("[DRY-RUN]", output)
        self.assertIn("Found 1 active subscription(s) eligible for billing.", output)
        self.assertIn("Created:             1", output)
        # Database count must be 0
        self.assertEqual(Invoice.objects.count(), 0)

    def test_run_billing_persists_invoices(self):
        """Verifies run_billing creates invoice and advances due subscription date."""
        out = StringIO()
        call_command("run_billing", stdout=out)
        output = out.getvalue()

        self.assertIn("[CREATED]", output)
        self.assertEqual(Invoice.objects.filter(subscription=self.sub_due).count(), 1)

        # Re-running the command skips duplicate without crashing
        out2 = StringIO()
        call_command("run_billing", stdout=out2)
        output2 = out2.getvalue()
        # sub_due date was advanced, so 0 subscriptions are due
        self.assertIn("Found 0 active subscription(s) eligible for billing.", output2)

    def test_run_billing_with_subscription_filter(self):
        """Verifies run_billing --subscription targets only the specified subscription."""
        out = StringIO()
        call_command("run_billing", "--subscription", str(self.sub_future.id), stdout=out)
        output = out.getvalue()

        self.assertIn(f"Found 1 active subscription(s) eligible for billing.", output)
        self.assertEqual(Invoice.objects.filter(subscription=self.sub_future).count(), 1)
        self.assertEqual(Invoice.objects.filter(subscription=self.sub_due).count(), 0)


from django.urls import reverse
from billing.forms import PaymentForm


class PaymentFormTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            email="staff_form@brightloop.local",
            password="Password@123",
            role=User.ROLE_STAFF,
        )
        self.customer = User.objects.create_user(
            email="cust_form@brightloop.local",
            password="Password@123",
            role=User.ROLE_CUSTOMER,
        )
        self.plan = Plan.objects.create(name="Standard", price=Decimal("100.00"), billing_period=Plan.PERIOD_MONTHLY)
        self.sub = Subscription.objects.create(customer=self.customer, plan=self.plan, status=Subscription.STATUS_ACTIVE)
        self.inv = Invoice.objects.create(
            subscription=self.sub,
            period_start=date.today(),
            period_end=date.today() + timedelta(days=30),
            status=Invoice.STATUS_CONFIRMED,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            due_date=date.today() + timedelta(days=14),
        )

    def test_form_initialization_with_balance(self):
        """Verifies PaymentForm initializes amount with remaining balance and shows helpful text."""
        form = PaymentForm(invoice=self.inv, user=self.staff_user)
        self.assertEqual(form.initial.get("amount"), Decimal("100.00"))
        self.assertIn("Outstanding balance: $100.00", form.fields["amount"].help_text)

    def test_form_valid_partial_payment(self):
        """Verifies partial payment is saved and reduces balance due while keeping status CONFIRMED."""
        data = {
            "amount": "40.00",
            "method": Payment.METHOD_CARD,
            "date": date.today().isoformat(),
            "reference": "TXN-PARTIAL-001",
        }
        form = PaymentForm(data=data, invoice=self.inv, user=self.staff_user)
        self.assertTrue(form.is_valid(), form.errors)
        pmt = form.save()

        self.assertEqual(pmt.amount, Decimal("40.00"))
        self.assertEqual(pmt.recorded_by, self.staff_user)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.balance_due, Decimal("60.00"))
        self.assertEqual(self.inv.amount_paid, Decimal("40.00"))
        self.assertEqual(self.inv.status, Invoice.STATUS_CONFIRMED)

    def test_form_full_payment_marks_invoice_paid(self):
        """Verifies full payment via form atomically marks invoice status as PAID."""
        data = {
            "amount": "100.00",
            "method": Payment.METHOD_BANK_TRANSFER,
            "date": date.today().isoformat(),
            "reference": "TXN-FULL-001",
        }
        form = PaymentForm(data=data, invoice=self.inv, user=self.staff_user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.inv.refresh_from_db()
        self.assertEqual(self.inv.balance_due, Decimal("0.00"))
        self.assertEqual(self.inv.amount_paid, Decimal("100.00"))
        self.assertEqual(self.inv.status, Invoice.STATUS_PAID)

    def test_form_overpayment_rejected(self):
        """Verifies payment exceeding invoice balance is rejected with form error."""
        data = {
            "amount": "120.00",
            "method": Payment.METHOD_CARD,
            "date": date.today().isoformat(),
        }
        form = PaymentForm(data=data, invoice=self.inv, user=self.staff_user)
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_form_zero_payment_rejected(self):
        """Verifies zero payment amount is rejected with form error."""
        data = {
            "amount": "0.00",
            "method": Payment.METHOD_CARD,
            "date": date.today().isoformat(),
        }
        form = PaymentForm(data=data, invoice=self.inv, user=self.staff_user)
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)


class BillingViewTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            email="staff_view@brightloop.local",
            password="Password@123",
            role=User.ROLE_STAFF,
            is_staff=True,
        )
        self.customer1 = User.objects.create_user(
            email="customer1_view@brightloop.local",
            password="Password@123",
            role=User.ROLE_CUSTOMER,
        )
        self.customer2 = User.objects.create_user(
            email="customer2_view@brightloop.local",
            password="Password@123",
            role=User.ROLE_CUSTOMER,
        )

        self.plan = Plan.objects.create(name="Pro View Plan", price=Decimal("150.00"), billing_period=Plan.PERIOD_MONTHLY)
        self.sub1 = Subscription.objects.create(customer=self.customer1, plan=self.plan, status=Subscription.STATUS_ACTIVE)
        self.sub2 = Subscription.objects.create(customer=self.customer2, plan=self.plan, status=Subscription.STATUS_ACTIVE)

        self.inv1 = Invoice.objects.create(
            subscription=self.sub1,
            period_start=date.today(),
            period_end=date.today() + timedelta(days=30),
            status=Invoice.STATUS_DRAFT,
            subtotal=Decimal("150.00"),
            total=Decimal("150.00"),
            due_date=date.today() + timedelta(days=14),
        )
        InvoiceLine.objects.create(
            invoice=self.inv1,
            description="Pro Service",
            quantity=1,
            unit_price=Decimal("150.00"),
            amount=Decimal("150.00"),
        )

        self.inv2 = Invoice.objects.create(
            subscription=self.sub2,
            period_start=date.today(),
            period_end=date.today() + timedelta(days=30),
            status=Invoice.STATUS_CONFIRMED,
            subtotal=Decimal("150.00"),
            total=Decimal("150.00"),
            due_date=date.today() + timedelta(days=14),
        )

    def test_invoice_list_view_data_scoping(self):
        """Verifies customer only sees own invoices, while staff sees all."""
        # Customer 1
        self.client.force_login(self.customer1)
        resp_cust = self.client.get(reverse("billing:list"))
        self.assertEqual(resp_cust.status_code, 200)
        self.assertContains(resp_cust, self.inv1.number)
        self.assertNotContains(resp_cust, self.inv2.number)

        # Staff
        self.client.force_login(self.staff_user)
        resp_staff = self.client.get(reverse("billing:list"))
        self.assertEqual(resp_staff.status_code, 200)
        self.assertContains(resp_staff, self.inv1.number)
        self.assertContains(resp_staff, self.inv2.number)

    def test_invoice_detail_view_permissions(self):
        """Verifies customer cannot access another customer's invoice (HTTP 404)."""
        self.client.force_login(self.customer1)
        # Attempt to access customer2's invoice
        resp = self.client.get(reverse("billing:detail", kwargs={"invoice_id": self.inv2.id}))
        self.assertEqual(resp.status_code, 404)

        # Access own invoice succeeds
        resp_own = self.client.get(reverse("billing:detail", kwargs={"invoice_id": self.inv1.id}))
        self.assertEqual(resp_own.status_code, 200)
        self.assertContains(resp_own, self.inv1.number)
        self.assertContains(resp_own, "Pro Service")

    def test_record_payment_view_staff_only(self):
        """Verifies staff can GET and POST payments, while customer receives HTTP 403."""
        # Customer is denied
        self.client.force_login(self.customer1)
        resp_denied = self.client.get(reverse("billing:record_payment", kwargs={"invoice_id": self.inv2.id}))
        self.assertEqual(resp_denied.status_code, 403)

        # Staff GET
        self.client.force_login(self.staff_user)
        resp_get = self.client.get(reverse("billing:record_payment", kwargs={"invoice_id": self.inv2.id}))
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "Record Payment")

        # Staff POST partial payment
        post_data = {
            "amount": "50.00",
            "method": Payment.METHOD_CARD,
            "date": date.today().isoformat(),
            "reference": "AUTH-1234",
        }
        resp_post = self.client.post(reverse("billing:record_payment", kwargs={"invoice_id": self.inv2.id}), post_data)
        self.assertRedirects(resp_post, reverse("billing:detail", kwargs={"invoice_id": self.inv2.id}))

        self.inv2.refresh_from_db()
        self.assertEqual(self.inv2.balance_due, Decimal("100.00"))
        self.assertEqual(self.inv2.amount_paid, Decimal("50.00"))

    def test_confirm_invoice_view(self):
        """Verifies staff can confirm DRAFT invoice."""
        self.client.force_login(self.staff_user)
        resp = self.client.post(reverse("billing:confirm", kwargs={"invoice_id": self.inv1.id}))
        self.assertRedirects(resp, reverse("billing:detail", kwargs={"invoice_id": self.inv1.id}))

        self.inv1.refresh_from_db()
        self.assertEqual(self.inv1.status, Invoice.STATUS_CONFIRMED)

    def test_payment_history_view(self):
        """Verifies payment history audit view renders recorded payments and filters."""
        Payment.objects.create(
            invoice=self.inv2,
            amount=Decimal("50.00"),
            method=Payment.METHOD_UPI,
            recorded_by=self.staff_user,
        )

        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse("billing:payment_history"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.inv2.number)
        self.assertContains(resp, "50.00")

    def test_invoice_outstanding_view(self):
        """Verifies outstanding invoices view lists unpaid invoices."""
        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse("billing:outstanding"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.inv2.number)

    def test_invoice_pdf_view_renders_successfully(self):
        """Verifies invoice PDF endpoint returns either application/pdf or print-friendly HTML."""
        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse("billing:pdf", kwargs={"invoice_id": self.inv1.id}))
        self.assertEqual(resp.status_code, 200)
        content_type = resp.headers.get("Content-Type", "")
        self.assertTrue("application/pdf" in content_type or "text/html" in content_type)


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
