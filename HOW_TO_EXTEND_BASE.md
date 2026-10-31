# How to Extend `base.html` — BrightLoop Developer Guide

Quick reference for teammates creating or upgrading pages in BrightLoop. Paste this into the group chat!

---

## 1. Quick Start: Template Boilerplate

Every page in your app should inherit from `base.html`:

```html
{% extends "base.html" %}
{% load static %}

{% block title %}My Feature — BrightLoop{% endblock %}

{% block content %}
<div class="container-fluid py-4">
  <div class="d-flex justify-content-between align-items-center mb-4">
    <div>
      <h2 class="fw-bold mb-1">My Feature Heading</h2>
      <p class="text-muted mb-0">Short description of this view</p>
    </div>
    <a href="#" class="btn btn-primary">Primary Action</a>
  </div>

  {# Form validation alerts (if page contains a form) #}
  {% include "includes/form_errors.html" %}

  <div class="card shadow-sm border-0">
    <div class="table-responsive">
      <table class="table table-hover align-middle mb-0">
        <thead class="table-light">
          <tr>
            <th>Item</th>
            <th>Status</th>
            <th class="text-end">Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for item in items %}
            <tr>
              <td>{{ item.name }}</td>
              <td><span class="badge badge-{{ item.status|lower }}">{{ item.status }}</span></td>
              <td class="text-end"><a href="#" class="btn btn-sm btn-outline-primary">View</a></td>
            </tr>
          {% empty %}
            <tr>
              <td colspan="3">
                {% include "includes/empty_state.html" with icon="inbox" message="No items found." %}
              </td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  {# Query-preserving pagination #}
  {% include "includes/pagination.html" %}
</div>
{% endblock %}
```

---

## 2. Preserved Blocks (Do NOT rename)

All teammates' pages depend on these exact block names:

| Block | Purpose | Example |
|---|---|---|
| `{% block title %}` | Browser tab title | `{% block title %}Invoices - BrightLoop{% endblock %}` |
| `{% block extra_head %}` | Page-specific CSS or `<meta>` | `{% block extra_head %}<style>...</style>{% endblock %}` |
| `{% block content %}` | Main page body | Your page HTML goes inside here |
| `{% block extra_js %}` | Page-specific scripts (runs after Bootstrap bundle) | `{% block extra_js %}<script>...</script>{% endblock %}` |

---

## 3. Responsive Layout: Desktop Sidebar & Mobile Offcanvas

- **Desktop (>= 992px):** Fixed left sidebar (`260px`), fixed white topbar (`56px`), main content offset automatically.
- **Mobile (< 992px):** Sidebar hidden by default. Toggled into a smooth Bootstrap 5 `offcanvas` drawer via the hamburger button in the topbar.
- **Top Bar:** Displays page title, active user email/name, role badge, Password Reset, and a secure POST Logout button.
- **100% Offline:** Local Bootstrap 5 bundle (`static/css/bootstrap.min.css` & `static/js/bootstrap.bundle.min.js`), no CDNs required.

---

## 4. Role-Based Navigation (`request.user.role`)

Sidebar links change based on the exact role values defined in `accounts/models.py` (`User.ROLE_*`):

- **`admin` (`User.ROLE_ADMIN = "admin"`):**
  - Dashboard (`dashboard:finance`)
  - Products (`catalog:product_list`)
  - Plans (`catalog:plan_list`)
  - Subscriptions (`subscriptions:list`)
  - Invoices (`billing:list`)
  - *Payments* (`TODO: billing:payment_list` - added as TODO until view is created)
  - *Reports* (`TODO: dashboard:report_list` - added as TODO until view is created)
  - *Intelligence* (`TODO: dashboard:intelligence` - added as TODO until view is created)
  - Staff (`accounts:staff_create`)
  - Django Admin (`/admin/`)

- **`staff` (`User.ROLE_STAFF = "staff"`):**
  - Dashboard (`dashboard:finance`)
  - *Customers* (`TODO: accounts:customer_list` - added as TODO until view is created)
  - Subscriptions (`subscriptions:list`)
  - Invoices (`billing:list`)
  - *Payments* (`TODO: billing:payment_list` - added as TODO until view is created)

- **`customer` (`User.ROLE_CUSTOMER = "customer"`):**
  - My Dashboard (`accounts:home`)
  - My Subscriptions (`subscriptions:list`)
  - My Invoices (`billing:list`)
  - Explore Plans (`catalog:plan_list`)

- **Active Link Highlighting:** Automatically matches `request.resolver_match` and marks the active link with `.active` and bright brand highlight.

---

## 5. Reusable Includes (`templates/includes/`)

### 1. Flash Messages (`messages.html`)
- Auto-included in `base.html`. No need to add it to your pages!
- Shows `messages.success(request, "Saved!")` as dismissible Bootstrap alerts with status icons.
- Automatically maps Django `error` tags to Bootstrap `alert-danger`.

### 2. Form Errors (`form_errors.html`)
Display field and non-field errors in forms:
```html
{% include "includes/form_errors.html" %}
{# or pass custom form: #}
{% include "includes/form_errors.html" with form=my_form %}
```

### 3. Pagination with Query Preservation (`pagination.html`)
Preserves existing filter/search query strings (`?search=foo&status=active&page=2`):
```html
{% include "includes/pagination.html" %}
```
Expects `page_obj` in view context (standard Django `ListView` or `Paginator`).

### 4. Empty State Placeholder (`empty_state.html`)
Friendly illustration and message for empty lists:
```html
{% include "includes/empty_state.html" with icon="search" message="No invoices match your filter." button_text="Clear Filter" button_url="/billing/" %}
```
Supported `icon` options: `"inbox"` (default), `"search"`, `"file"`, `"users"`, `"chart"`.

---

## 6. Design Tokens & Styling (`brightloop.css`)

**Rule:** Always use CSS variables (`var(--bl-*)`). Never hardcode hex colors or pixel sizes in custom components:

| Category | CSS Variable | Value / Purpose |
|---|---|---|
| **Brand Colors** | `var(--bl-brand-primary)` | Royal Blue (`#2563eb`) |
| | `var(--bl-brand-primary-hover)` | Darker Blue (`#1d4ed8`) |
| | `var(--bl-brand-secondary)` | Slate Gray (`#475569`) |
| | `var(--bl-brand-accent)` | Sky Blue (`#0ea5e9`) |
| **Status Colors** | `var(--bl-color-active)` | Green (`#10b981`) |
| | `var(--bl-color-paid)` | Blue (`#2563eb`) |
| | `var(--bl-color-draft)` | Slate Muted (`#94a3b8`) |
| | `var(--bl-color-overdue)` | Red (`#ef4444`) |
| | `var(--bl-color-closed)` | Charcoal (`#334155`) |
| | `var(--bl-color-warning)` | Amber (`#f59e0b`) |
| **Backgrounds** | `var(--bl-bg-body)` | `#f8fafc` |
| | `var(--bl-bg-card)` | `#ffffff` |
| | `var(--bl-bg-sidebar)` | `#1e293b` |
| **Text** | `var(--bl-text-primary)` | `#1e293b` |
| | `var(--bl-text-muted)` | `#94a3b8` |
| **Radii** | `var(--bl-radius-sm)` / `md` / `lg` | `0.375rem` / `0.5rem` / `0.75rem` |
| **Spacing** | `var(--bl-spacing-xs)` to `xl` | `0.25rem` to `2.5rem` |

---

## 7. Status Badges

Add these badge classes directly to your template spans:
```html
<span class="badge badge-draft">Draft</span>
<span class="badge badge-active">Active</span>
<span class="badge badge-paid">Paid</span>
<span class="badge badge-overdue">Overdue</span>
<span class="badge badge-closed">Closed</span>
<span class="badge badge-pending">Pending</span>
```

---

## 8. Mobile Table Rule

**Always wrap every `<table>` in `<div class="table-responsive">`**:
```html
<div class="table-responsive">
  <table class="table table-hover align-middle mb-0">
    ...
  </table>
</div>
```
This guarantees that tables scroll smoothly on small mobile screens without breaking the layout.
