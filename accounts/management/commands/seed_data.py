"""
accounts/management/commands/seed_data.py
=========================================
Purpose:
    Database seeder for the BrightLoop hackathon project.
    Populates:
      - 1 Admin user (admin@brightloop.local)
      - 2 Staff users (staff1@..., staff2@...)
      - 20 Customer users (customer1@... to customer20@...)
      - Catalog entities: Products, Variants, Plans, Taxes, Discounts, Quotation Templates
      - Realistic starter subscriptions and invoices
    
    Optional --big flag:
      Uses bulk_create to quickly populate 3,000+ subscriptions and 10,000+ invoices
      for high-scale performance testing and aggregate dashboard validation.

Usage:
    python manage.py seed_data
    python manage.py seed_data --big
"""

import random
from decimal import Decimal
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from catalog.models import Product, ProductVariant, Plan, Tax, Discount
from subscriptions.models import QuotationTemplate, TemplateLine, Subscription, SubscriptionLine
from billing.models import Invoice, InvoiceLine, Payment

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds database with demo accounts, catalog, subscriptions, invoices, and payments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--big",
            action="store_true",
            help="Generates 3,000+ subscriptions and 10,000+ invoices using bulk_create.",
        )

    def handle(self, *args, **options):
        is_big = options.get("big", False)
        self.stdout.write(self.style.NOTICE("===> Starting BrightLoop Database Seeder..."))

        # Default standard password that satisfies CustomComplexityValidator (>8 chars, upper, lower, special)
        DEFAULT_PWD = "SecurePassword@123"

        # ----------------------------------------------------------------------
        # 1. Create Users (1 Admin, 2 Staff, 20 Customers)
        # ----------------------------------------------------------------------
        self.stdout.write("Creating users...")

        admin_user, _ = User.objects.get_or_create(
            email="admin@brightloop.local",
            defaults={
                "first_name": "System",
                "last_name": "Admin",
                "role": User.ROLE_ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        admin_user.set_password(DEFAULT_PWD)
        admin_user.save()

        staff_users = []
        for i in (1, 2):
            staff, _ = User.objects.get_or_create(
                email=f"staff{i}@brightloop.local",
                defaults={
                    "first_name": "Operations",
                    "last_name": f"Staff-{i}",
                    "role": User.ROLE_STAFF,
                    "is_staff": True,
                    "is_superuser": False,
                },
            )
            staff.set_password(DEFAULT_PWD)
            staff.save()
            staff_users.append(staff)

        customer_users = []
        for i in range(1, 21):
            cust, _ = User.objects.get_or_create(
                email=f"customer{i}@brightloop.local",
                defaults={
                    "first_name": f"Customer",
                    "last_name": f"User-{i}",
                    "role": User.ROLE_CUSTOMER,
                    "is_staff": False,
                    "is_superuser": False,
                },
            )
            cust.set_password(DEFAULT_PWD)
            cust.save()
            customer_users.append(cust)

        self.stdout.write(self.style.SUCCESS(f"Created 1 Admin, 2 Staff, and {len(customer_users)} Customers."))

        # ----------------------------------------------------------------------
        # 2. Create Catalog (Taxes, Products, Variants, Plans, Discounts)
        # ----------------------------------------------------------------------
        self.stdout.write("Creating catalog data...")

        tax_gst, _ = Tax.objects.get_or_create(name="GST 18%", defaults={"rate": Decimal("18.00")})
        tax_vat, _ = Tax.objects.get_or_create(name="VAT 5%", defaults={"rate": Decimal("5.00")})
        tax_zero, _ = Tax.objects.get_or_create(name="Zero Tax", defaults={"rate": Decimal("0.00")})

        p1, _ = Product.objects.get_or_create(
            name="Cloud Hosting Pro",
            defaults={"type": Product.TYPE_SERVICE, "sales_price": Decimal("99.00"), "cost_price": Decimal("30.00")},
        )
        p2, _ = Product.objects.get_or_create(
            name="Enterprise SaaS License",
            defaults={"type": Product.TYPE_DIGITAL, "sales_price": Decimal("299.00"), "cost_price": Decimal("50.00")},
        )
        p3, _ = Product.objects.get_or_create(
            name="Priority 24/7 Support",
            defaults={"type": Product.TYPE_SERVICE, "sales_price": Decimal("149.00"), "cost_price": Decimal("40.00")},
        )
        p4, _ = Product.objects.get_or_create(
            name="Developer API Pack",
            defaults={"type": Product.TYPE_DIGITAL, "sales_price": Decimal("49.00"), "cost_price": Decimal("5.00")},
        )

        ProductVariant.objects.get_or_create(
            product=p1,
            attribute="Memory",
            value="32GB RAM",
            defaults={"extra_price": Decimal("40.00")},
        )
        ProductVariant.objects.get_or_create(
            product=p2,
            attribute="Brand",
            value="Odoo Connector",
            defaults={"extra_price": Decimal("560.00")},
        )

        plan_daily, _ = Plan.objects.get_or_create(
            name="Daily Flexible",
            defaults={"price": Decimal("5.00"), "billing_period": Plan.PERIOD_DAILY, "renewable": True},
        )
        plan_weekly, _ = Plan.objects.get_or_create(
            name="Weekly Starter",
            defaults={"price": Decimal("25.00"), "billing_period": Plan.PERIOD_WEEKLY, "renewable": True},
        )
        plan_monthly, _ = Plan.objects.get_or_create(
            name="Monthly Professional",
            defaults={"price": Decimal("99.00"), "billing_period": Plan.PERIOD_MONTHLY, "renewable": True},
        )
        plan_yearly, _ = Plan.objects.get_or_create(
            name="Yearly Enterprise",
            defaults={"price": Decimal("999.00"), "billing_period": Plan.PERIOD_YEARLY, "renewable": True},
        )

        disc_launch, _ = Discount.objects.get_or_create(
            name="LAUNCH10",
            defaults={
                "type": Discount.TYPE_PERCENT,
                "value": Decimal("10.00"),
                "applies_to": Discount.APPLIES_SUBSCRIPTIONS,
                "min_purchase": Decimal("50.00"),
                "usage_limit": 500,
            },
        )
        disc_fixed, _ = Discount.objects.get_or_create(
            name="SAVE50",
            defaults={
                "type": Discount.TYPE_FIXED,
                "value": Decimal("50.00"),
                "applies_to": Discount.APPLIES_SUBSCRIPTIONS,
                "min_purchase": Decimal("200.00"),
                "usage_limit": 100,
            },
        )

        # Quotation template
        tpl, _ = QuotationTemplate.objects.get_or_create(
            name="Enterprise Core Bundle",
            defaults={"plan": plan_monthly, "validity_days": 30},
        )
        TemplateLine.objects.get_or_create(template=tpl, product=p2, defaults={"quantity": 1})
        TemplateLine.objects.get_or_create(template=tpl, product=p3, defaults={"quantity": 1})

        # ----------------------------------------------------------------------
        # 3. Create Sample Subscriptions & Invoices (Realistic Seed)
        # ----------------------------------------------------------------------
        today = timezone.localdate()
        plans_pool = [plan_daily, plan_weekly, plan_monthly, plan_yearly]
        products_pool = [p1, p2, p3, p4]

        self.stdout.write("Creating starter subscriptions and invoices...")
        statuses = [
            Subscription.STATUS_ACTIVE,
            Subscription.STATUS_ACTIVE,
            Subscription.STATUS_ACTIVE,
            Subscription.STATUS_CONFIRMED,
            Subscription.STATUS_QUOTATION,
            Subscription.STATUS_DRAFT,
            Subscription.STATUS_CLOSED,
        ]

        def to_money(val):
            return Decimal(str(val)).quantize(Decimal("0.01"))

        sample_subs = []
        for idx, customer in enumerate(customer_users[:12]):
            chosen_plan = plans_pool[idx % len(plans_pool)]
            chosen_status = statuses[idx % len(statuses)]
            sub_date = today - timedelta(days=idx * 15)

            sub = Subscription.objects.create(
                customer=customer,
                plan=chosen_plan,
                start_date=sub_date,
                status=chosen_status,
                payment_terms="Net 15",
                next_invoice_date=today + timedelta(days=(idx % 7) - 3),
            )
            sample_subs.append(sub)

            # Add line item
            prod = products_pool[idx % len(products_pool)]
            SubscriptionLine.objects.create(
                subscription=sub,
                product=prod,
                quantity=1,
                unit_price=prod.sales_price,
                tax=tax_gst,
                amount=prod.sales_price,
            )

            # Generate sample invoices for active/confirmed subscriptions
            if chosen_status in [Subscription.STATUS_ACTIVE, Subscription.STATUS_CONFIRMED]:
                # Period 1 (Settled)
                p1_start = sub_date
                p1_end = sub_date + timedelta(days=30)
                inv1_tax = to_money(chosen_plan.price * Decimal("0.18"))
                inv1_total = to_money(chosen_plan.price + inv1_tax)

                inv1 = Invoice.objects.create(
                    subscription=sub,
                    period_start=p1_start,
                    period_end=p1_end,
                    status=Invoice.STATUS_PAID,
                    subtotal=chosen_plan.price,
                    discount_amount=Decimal("0.00"),
                    tax_amount=inv1_tax,
                    total=inv1_total,
                    due_date=p1_start + timedelta(days=14),
                )
                InvoiceLine.objects.create(
                    invoice=inv1,
                    product=prod,
                    description=f"{prod.name} ({chosen_plan.name})",
                    quantity=1,
                    unit_price=chosen_plan.price,
                    tax_rate=Decimal("18.00"),
                    amount=chosen_plan.price,
                )
                # Full Payment
                Payment.objects.create(
                    invoice=inv1,
                    method=Payment.METHOD_CREDIT_CARD,
                    amount=inv1.total,
                    date=p1_start + timedelta(days=2),
                    note="Autopay settled",
                )

                # Period 2 (Recent - maybe Overdue or Confirmed)
                p2_start = p1_end + timedelta(days=1)
                p2_end = p2_start + timedelta(days=30)
                is_overdue_sample = (idx % 2 == 0)
                inv2_status = Invoice.STATUS_CONFIRMED
                inv2_due = today - timedelta(days=5) if is_overdue_sample else today + timedelta(days=10)
                disc_val = Decimal("10.00") if chosen_plan.price > Decimal("20.00") else Decimal("0.00")
                inv2_subtotal = chosen_plan.price
                inv2_tax = to_money((inv2_subtotal - disc_val) * Decimal("0.18"))
                inv2_total = to_money(inv2_subtotal - disc_val + inv2_tax)

                inv2 = Invoice.objects.create(
                    subscription=sub,
                    period_start=p2_start,
                    period_end=p2_end,
                    status=inv2_status,
                    subtotal=inv2_subtotal,
                    discount_amount=disc_val,
                    tax_amount=inv2_tax,
                    total=inv2_total,
                    due_date=inv2_due,
                )
                InvoiceLine.objects.create(
                    invoice=inv2,
                    product=prod,
                    description=f"{prod.name} (Recurring billing)",
                    quantity=1,
                    unit_price=chosen_plan.price,
                    tax_rate=Decimal("18.00"),
                    amount=chosen_plan.price,
                )

                # Partial payment on some invoices
                if idx % 3 == 0:
                    partial = Decimal("20.00")
                    if partial < inv2.total:
                        Payment.objects.create(
                            invoice=inv2,
                            method=Payment.METHOD_UPI,
                            amount=partial,
                            date=today,
                            note="Partial installment",
                        )

        self.stdout.write(self.style.SUCCESS("Base seed data generated successfully."))

        # ----------------------------------------------------------------------
        # 4. Optional --big Scale Data (3,000+ Subscriptions, 10,000+ Invoices)
        # ----------------------------------------------------------------------
        if is_big:
            existing_big = Subscription.objects.filter(number__startswith="SUB-BIG-").count()
            if existing_big >= 3000:
                self.stdout.write(self.style.SUCCESS(f"Scale dataset already exists in database ({existing_big} subscriptions). Skipping duplicate generation."))
            else:
                self.stdout.write(self.style.WARNING("===> Generating --big scale dataset via bulk_create..."))
            
                # Target counts
                TARGET_SUBSCRIPTIONS = 3200
                INVOICES_PER_SUB = 4  # 3200 * 4 = 12,800 invoices (>10,000)

                bulk_subs = []
                for i in range(TARGET_SUBSCRIPTIONS):
                    c = customer_users[i % len(customer_users)]
                    p = plans_pool[i % len(plans_pool)]
                    s_status = random.choice([Subscription.STATUS_ACTIVE, Subscription.STATUS_ACTIVE, Subscription.STATUS_CONFIRMED, Subscription.STATUS_DRAFT, Subscription.STATUS_CLOSED])
                    s_date = today - timedelta(days=random.randint(30, 700))
                    s_next = today + timedelta(days=random.randint(-15, 30))

                    sub_obj = Subscription(
                        number=f"SUB-BIG-{i:05d}",
                        customer=c,
                        plan=p,
                        start_date=s_date,
                        status=s_status,
                        payment_terms="Net 15",
                        next_invoice_date=s_next,
                    )
                    bulk_subs.append(sub_obj)

                self.stdout.write(f"Bulk creating {len(bulk_subs)} subscriptions...")
                Subscription.objects.bulk_create(bulk_subs, batch_size=1000, ignore_conflicts=True)
                created_subs = list(Subscription.objects.filter(number__startswith="SUB-BIG-"))
                self.stdout.write(self.style.SUCCESS(f"Saved {len(created_subs)} bulk subscriptions."))

                # Now create bulk invoices
                self.stdout.write("Generating 12,000+ bulk invoices...")
                bulk_invoices = []
                inv_counter = 0

                for sub in created_subs:
                    plan_price = sub.plan.price
                    sub_tax = to_money(plan_price * Decimal("0.18"))
                    sub_tot = to_money(plan_price + sub_tax)

                    for m in range(INVOICES_PER_SUB):
                        inv_counter += 1
                        p_start = sub.start_date + timedelta(days=m * 30)
                        p_end = p_start + timedelta(days=30)
                        due = p_start + timedelta(days=14)

                        # Determine realistic statuses
                        if due < today - timedelta(days=30):
                            status = Invoice.STATUS_PAID
                        elif due < today:
                            status = random.choice([Invoice.STATUS_PAID, Invoice.STATUS_CONFIRMED])
                        else:
                            status = random.choice([Invoice.STATUS_CONFIRMED, Invoice.STATUS_DRAFT])

                        inv_obj = Invoice(
                            number=f"INV-BIG-{inv_counter:06d}",
                            subscription=sub,
                            status=status,
                            period_start=p_start,
                            period_end=p_end,
                            subtotal=plan_price,
                            discount_amount=Decimal("0.00"),
                            tax_amount=sub_tax,
                            total=sub_tot,
                            due_date=due,
                        )
                        bulk_invoices.append(inv_obj)

                self.stdout.write(f"Bulk inserting {len(bulk_invoices)} invoices...")
                Invoice.objects.bulk_create(bulk_invoices, batch_size=2000, ignore_conflicts=True)
                self.stdout.write(self.style.SUCCESS(f"Successfully populated {len(bulk_invoices)} invoices!"))

                # Bulk create payments for paid invoices
                self.stdout.write("Populating payments for settled invoices...")
                paid_invoices = list(Invoice.objects.filter(number__startswith="INV-BIG-", status=Invoice.STATUS_PAID)[:6000])
                bulk_payments = []
                for p_inv in paid_invoices:
                    bulk_payments.append(
                        Payment(
                            invoice=p_inv,
                            method=random.choice([Payment.METHOD_CREDIT_CARD, Payment.METHOD_UPI, Payment.METHOD_BANK_TRANSFER]),
                            amount=p_inv.total,
                            date=p_inv.due_date - timedelta(days=2),
                            note="Bulk test payment",
                        )
                    )

                Payment.objects.bulk_create(bulk_payments, batch_size=2000, ignore_conflicts=True)
                self.stdout.write(self.style.SUCCESS(f"Saved {len(bulk_payments)} bulk payments."))

        self.stdout.write(self.style.SUCCESS("===> Seed data command completed successfully!"))
        self.stdout.write("\nCredentials for testing:")
        self.stdout.write("  Admin:    admin@brightloop.local    / SecurePassword@123")
        self.stdout.write("  Staff:    staff1@brightloop.local   / SecurePassword@123")
        self.stdout.write("  Customer: customer1@brightloop.local / SecurePassword@123")
