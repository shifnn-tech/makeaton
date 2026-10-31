# BrightLoop - Subscription Management System

> **8-Hour Hackathon Starter Skeleton**  
> Built with Python 3, Django, SQLite, server-rendered Django templates, and local Bootstrap 5 (100% offline, zero CDN dependencies).

---

## 🌟 Overview & Architecture

BrightLoop is a modular subscription management and recurring billing engine. The project is split into **5 independent apps** so a team of 4 developers can work in parallel with minimal Git merge conflicts:
BrightLoop is a modular subscription management and recurring billing engine. The project is split into **independent apps** so developers can work in parallel with minimal Git merge conflicts:

| Developer | App Area | Primary Responsibilities |
|---|---|---|
| **Dev 1** | `accounts/` | Custom User model, email login, roles (Admin/Staff/Customer), password reset flow, query isolation helper |
| **Dev 2** | `catalog/` | Products, variants, subscription plans, taxes, discounts, and model validation |
| **Dev 3** | `subscriptions/` | Quotations, subscription contracts, line items, status state-machine transitions |
| **Dev 4** | `billing/` & `dashboard/` | Invoices, payments, automated billing runner stub, and executive finance analytics |
| App Area | Primary Responsibilities |
|---|---|
| `accounts/` | Custom User model, email login, roles (Admin/Staff/Customer), password reset flow, query isolation helper |
| `catalog/` | Products, variants, subscription plans, taxes, discounts, and model validation |
| `subscriptions/` | Quotations, subscription contracts, line items, status state-machine transitions |
| `billing/` & `dashboard/` | Invoices, payments, automated billing runner stub, and executive finance analytics |
| `intelligence/` | Revenue intelligence, ARR/MRR metrics, cash flow forecasting, leak detection, and pricing simulator |
| `portal/` | Role dashboards (Admin/Staff/Customer), cross-model search, billing calendar, customer management, audit log, notifications, and CSV export |

---

## 🚀 Quickstart: Setup & Run (Step-by-Step)

### 1. Prerequisites
- Python 3.10+ (Tested with Python 3.14)
- Git

### 2. Clone the Repository
```bash
git clone https://github.com/shifnn-tech/makeaton.git
cd makeaton
```

### 3. Create and Activate Virtual Environment
- **On Windows (PowerShell):**
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```
- **On macOS / Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Apply Database Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Seed Demo Data
Populate the database with sample products, plans, taxes, discounts, 1 Admin, 2 Staff, and 20 Customer accounts:
Populate the database with sample products, plans, taxes, discounts, 1 Admin, 2 Staff, 20 Customer accounts, realistic overdue & upcoming subscriptions/invoices, notifications, and audit log events:
```bash
python manage.py seed_data
```

*(Optional)* To test heavy database performance with **3,000+ subscriptions and 10,000+ invoices** via `bulk_create`:
```bash
python manage.py seed_data --big
```

### 7. Run the Development Server
```bash
python manage.py runserver
```
Visit **http://127.0.0.1:8000/** in your browser.

---

## 🔑 Default Seed Credentials

All seed accounts use the password: `SecurePassword@123`

| Role | Email | Password | Access Privileges |
|---|---|---|---|
| **Admin** | `admin@brightloop.local` | `SecurePassword@123` | Full access, Django Admin, Create Staff, Finance Dashboard |
| **Staff** | `staff1@brightloop.local` | `SecurePassword@123` | Manage Subscriptions, Invoices, Finance Dashboard |
| **Customer** | `customer1@brightloop.local` | `SecurePassword@123` | Self-service portal (own subscriptions and invoices only) |
| **Admin** | `admin@brightloop.local` | `SecurePassword@123` | Full access, Django Admin, Staff Creation, Executive Dashboard, Intelligence, Reports |
| **Staff** | `staff1@brightloop.local` | `SecurePassword@123` | Manage Subscriptions, Invoices, Customer Directory, Operations Desk, Reports |
| **Customer** | `customer1@brightloop.local` | `SecurePassword@123` | Self-service portal (own subscriptions, invoices, and renewal calendar only) |

---

## 📂 App Breakdown & File Directory

### 1. `accounts/` (Authentication & Role Security)
- **`models.py`**: Custom `User` model (`AbstractUser`) using `email` as `USERNAME_FIELD` and a `role` field (`admin`, `staff`, `customer`).
- **`validators.py`**: `CustomComplexityValidator` requiring >8 characters, uppercase, lowercase, and special characters.
- **`decorators.py`**: `@role_required("admin", "staff")` and `RoleRequiredMixin` to enforce RBAC on views.
- **`utils.py`**: `filter_by_user(queryset, user)` ensures customers only ever see their own records.
- **`forms.py`**: `CustomerSignUpForm` (creates customers only), `LoginForm`, and `StaffCreationForm` (admin only).
- **`views.py`**: Sign up, sign in, sign out, staff creation, and role-aware landing page.
- **`urls.py`**: Authentication routes and Django's built-in password reset views.
- **`admin.py`**: Custom `UserAdmin` organized by email and roles.
- **`management/commands/seed_data.py`**: Database seeder with sample accounts and `--big` scale support.
- **`management/commands/seed_data.py`**: Database seeder with sample accounts, catalog, overdue invoices, upcoming renewals, notifications, audit log entries, and `--big` scale support.

### 2. `catalog/` (Products, Plans, Pricing Rules)
- **`models.py`**:
  - `Product`: Base sellable item (`service`, `physical`, `digital`) with sales and cost price.
  - `ProductVariant`: Variations (e.g. Attribute='Brand', Value='Odoo', Extra Price=560).
  - `Plan`: Recurring subscription plans (`daily`, `weekly`, `monthly`, `yearly`) with auto-close, closable, pausable, and renewable flags.
  - `Tax`: Percentage rate between 0.00% and 100.00%.
  - `Discount`: Fixed or percentage discounts with start/end dates, minimum purchase, usage limits, and product targeting.
  - *Model Validators*: Non-negative prices, valid date ranges, and percentage at most 100%.
- **`views.py` & `urls.py`**: Publicly browsable subscription plan and product catalogs.
- **`admin.py`**: Admin panels with inline variant editing.

### 3. `subscriptions/` (Contracts & Quotations)
- **`models.py`**:
  - `QuotationTemplate` & `TemplateLine`: Bundles to quickly quote multi-item subscriptions.
  - `Subscription`: Main recurring contract. Auto-generates unique number (`SUB-YYYYMM-XXXX`). Includes indexed fields on `status`, `customer`, and `next_invoice_date`.
  - `SubscriptionLine`: Itemized products, quantities, taxes, and amounts.
  - *State Machine*: `Draft -> Quotation -> Confirmed -> Active -> Closed` defined in a single transition dictionary. `change_status()` rejects invalid transitions.
- **`views.py` & `urls.py`**: Scoped views where customers only access their own contracts.
- **`admin.py`**: Admin setup with `SubscriptionLineInline`.

### 4. `billing/` (Invoices, Payments & Automation)
- **`models.py`**:
  - `Invoice`: Billing statement with `UniqueConstraint(fields=['subscription', 'period_start'])` to prevent double-billing.
  - `InvoiceLine`: Itemized invoice lines with tax and unit amounts.
  - `Payment`: Financial transaction records with strict validation (must be positive and cannot exceed remaining balance). Automatically transitions invoice to `Paid` once settled.
  - *Dynamic Properties*: `amount_paid` and `balance_due` calculated dynamically (never cached stale).
  - *QuerySet Helper*: `Invoice.objects.overdue()` queries `due_date < today` and `status != 'Paid'`.
- **`services.py`**: Atomic transaction stub `generate_invoice(subscription)` with detailed step-by-step instructions.
- **`management/commands/run_billing.py`**: Runner command finding active subscriptions with `next_invoice_date <= today`.
- **`admin.py`**: Invoice administration with payment and invoice line inlines.

### 5. `dashboard/` (Executive & Financial Analytics)
- **`views.py`**:
  - Computes Active Subscriptions, Total Revenue, Outstanding Amount, and Overdue Invoices.
  - Optimized with database-level `aggregate(Sum(...))`, `select_related(...)` to eliminate N+1 queries, and `Paginator` for instant page loads.
- **`templates/dashboard/finance.html`**: Financial KPI metric cards, urgent overdue watchlist, and paginated invoice table.

### 6. UI & Styling (`templates/` & `static/`)
- **`templates/base.html`**: Bootstrap 5 shell with brand CSS variables, responsive role-based navigation, user dropdown, messages display, and print styles.
- **`static/css/bootstrap.min.css` & `static/js/bootstrap.bundle.min.js`**: Local Bootstrap 5 files for 100% offline development.
- **`static/css/style.css`**: CSS custom variables (`--primary-color`), role badges, and print media rules.
- **`templates/includes/form_errors.html`**: Reusable form error display.
- **`templates/includes/pagination.html`**: Reusable pagination controls.
### 6. `intelligence/` (Revenue Intelligence & Analytics)
- **`models.py`** & **`services.py`**: Algorithms for metrics computation, churn analysis, MRR/ARR tracking, and forecasting.
- **`views.py` & `urls.py`**:
  - **Revenue Metrics** (`intelligence:dashboard`): Net ARR, MRR, churn rate, and LTV trends.
  - **Forecast & Health** (`intelligence:forecast`): 30/60/90-day cash projections and subscription health scoring.
  - **Leak Detector** (`intelligence:leaks`): Identifies unbilled renewals, failed payments, and revenue gaps.
  - **What-If Simulator** (`intelligence:simulator`): Interactive pricing tier adjustments and revenue growth modeling.

### 7. `portal/` (Unified Role Portals, Operations, Audit & Reports)
- **`models.py`**:
  - `Notification`: In-app alerts with recipient user, message, target URL link, read flag, and timestamp.
  - `AuditLog`: System-wide audit trail recording model name, record ID, user, action (`create`, `update`, `delete`), description, and timestamp.
- **`signals.py`**: Automatic `post_save` and `post_delete` signals connected for `Subscription`, `Invoice`, `Payment`, and `Discount` logging changes to `AuditLog`. Registered via `PortalConfig.ready()`.
- **`context_processors.py`**: `notifications_context` providing `unread_notifications_count` and `recent_unread_notifications` across all templates.
- **`management/commands/create_reminders.py`**: Scans for maturing invoices (due within `--days`, default 7) and overdue invoices to generate idempotent in-app notifications without duplicates.
- **`views.py` & `urls.py`**:
  - **Role Landing View** (`portal:landing`): Redirects logged-in users directly to their designated dashboard.
  - **Admin Control Center** (`portal:admin_dashboard`): High-level aggregates (platform users, active contracts, open invoices, settled revenue) with deep links to finance and intelligence tools.
  - **Staff Operations Desk** (`portal:staff_dashboard`): Operational queues highlighting overdue invoices, invoices due soon, and recent contracts.
  - **Customer Dashboard** (`portal:customer_dashboard`): Secure self-service overview showing active plans, upcoming renewal date, outstanding invoices, and settled receipts.
  - **Global Search** (`portal:search`): Top bar search input handling `?q=` queries across customer emails/names, subscription numbers, and invoice numbers using `Q` objects and role-based filtering.
  - **Billing Calendar** (`portal:calendar`): Subscriptions renewing in the next 30 days, grouped by week with projected revenue totals.
  - **Customer Directory & Profile** (`portal:customer_list`, `portal:customer_detail`): Staff/Admin customer management with pagination, search, and drill-downs into contracts, statements, and payment histories.
  - **Activity Timeline** (`portal:activity_timeline`): Paginated audit log explorer with filtering by model type, action, and date range.
  - **Notifications Center** (`portal:notifications`, `portal:notification_read`, `portal:notification_mark_all_read`): Paginated notification inbox with filter tabs (All, Unread, Read) and mark-as-read actions.
  - **Business Reports & CSV Export** (`portal:reports`): Audit extracts for subscriptions, invoices, and payments with date/status filters, metric summaries, and one-click CSV download using Python's `csv` module.

### 8. UI, Design System & Styling (`templates/` & `static/`)
- **`templates/base.html`**: Unified layout shell with fixed topbar, responsive sidebar, user avatar, global search box, and notification bell dropdown with real-time unread badges.
- **`templates/includes/_sidebar_content.html`**: Dynamic sidebar navigation customized per role (`admin`, `staff`, `customer`, anonymous) with section headers, SVG icons, and active state tracking.
- **`static/css/brightloop.css`**: Complete design system with CSS custom properties (`var(--bl-*)`), button/card/table styling, status badge aliases (`badge-status-*`), and mobile responsiveness rules (<992px phone width).
- **`static/css/bootstrap.min.css` & `static/js/bootstrap.bundle.min.js`**: Local Bootstrap 5 bundle (100% offline, zero CDN dependencies).
- **`static/css/style.css`**: Core brand variables, badges, and print media rules.
- **`templates/includes/empty_state.html`**: Reusable empty state placeholder component.
- **`templates/includes/form_errors.html`**: Standardized form validation error alerts.
- **`templates/includes/pagination.html`**: Bootstrap-styled pagination navigation.
- **`templates/includes/messages.html`**: Auto-dismissing Django alert messages.

---

## ⚡ Background Commands & Automation

1. **Run Recurring Billing Cycle:**
   ```bash
   python manage.py run_billing
   ```
   *(Add `--dry-run` to simulate without saving changes)*

2. **Trigger Database Seeder:**
3. **Trigger Automated Reminders (Due Soon & Overdue Invoices):**
   ```bash
   python manage.py create_reminders --days 7
   ```
   *(Generates non-duplicate in-app notifications for invoices due within 7 days and overdue invoices)*

3. **Trigger Database Seeder:**
   ```bash
   python manage.py seed_data
   ```
   *(Add `--big` for high-volume benchmark testing with 3,000+ subscriptions, 12,000+ invoices, bulk payments, notifications, and audit records)*

3. **Check System Health:**
4. **Check System Health:**
   ```bash
   python manage.py check
   ```
