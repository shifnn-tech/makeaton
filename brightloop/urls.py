"""
brightloop/urls.py
==================
Purpose:
    Main URL router for the BrightLoop project.
    Routes requests to their respective app-level URL modules:
      - /            -> accounts.urls (Home & Auth)
      - /catalog/    -> catalog.urls (Plans & Products)
      - /subs/       -> subscriptions.urls (Contracts & Quotations)
      - /billing/    -> billing.urls (Invoices & Payments)
      - /dashboard/  -> dashboard.urls (Finance Analytics)
      - /intelligence/ -> intelligence.urls (Revenue Intelligence)
      - /portal/     -> portal.urls (Role Dashboards, Global Search, Calendar & Customer Portal)
      - /admin/      -> Django built-in Administration
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Django Admin site
    path("admin/", admin.site.urls),

    # Accounts & Authentication (also handles root landing page)
    path("", include("accounts.urls", namespace="accounts")),

    # Catalog & Plans
    path("catalog/", include("catalog.urls", namespace="catalog")),

    # Subscriptions & Quotations
    path("subscriptions/", include("subscriptions.urls", namespace="subscriptions")),

    # Billing, Invoices & Payments
    path("billing/", include("billing.urls", namespace="billing")),

    # Analytics & Finance Dashboard
    path("dashboard/", include("dashboard.urls", namespace="dashboard")),

    # Revenue Intelligence (Person 3)
    path("intelligence/", include("intelligence.urls", namespace="intelligence")),

    # Unified Portal (Role Dashboards, Global Search, Calendar & Customer Management)
    path("portal/", include("portal.urls", namespace="portal")),
]
