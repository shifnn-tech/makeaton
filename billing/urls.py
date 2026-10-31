"""
billing/urls.py
===============
Purpose:
    URL configuration for the billing app.
    Defines routes for invoice management, payment recording, audit history, and PDF output.
"""

from django.urls import path
from . import views

app_name = "billing"

urlpatterns = [
    # Invoice listings
    path("", views.invoice_list_view, name="list"),
    path("outstanding/", views.invoice_outstanding_view, name="outstanding"),

    # Invoice detail & actions
    path("<int:invoice_id>/", views.invoice_detail_view, name="detail"),
    path("<int:invoice_id>/pay/", views.invoice_pay_view, name="pay"),
    path("<int:invoice_id>/record-payment/", views.record_payment_view, name="record_payment"),
    path("<int:invoice_id>/confirm/", views.confirm_invoice_view, name="confirm"),
    path("<int:invoice_id>/pdf/", views.invoice_pdf_view, name="pdf"),

    # Payment history
    path("payments/", views.payment_history_view, name="payment_history"),
]
