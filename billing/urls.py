"""
billing/urls.py
===============
Purpose:
    URL routes for invoice management, viewing, and online payments.
"""

from django.urls import path
from . import views

app_name = "billing"

urlpatterns = [
    path("", views.invoice_list_view, name="list"),
    path("<int:invoice_id>/", views.invoice_detail_view, name="detail"),
    path("<int:invoice_id>/pay/", views.invoice_pay_view, name="pay"),
]
