"""
subscriptions/urls.py
=====================
Purpose:
    URL routes for viewing subscription contracts, subscribing, and status transitions.
"""

from django.urls import path
from . import views

app_name = "subscriptions"

urlpatterns = [
    path("", views.subscription_list_view, name="list"),
    path("<int:subscription_id>/", views.subscription_detail_view, name="detail"),
    path("subscribe/<int:plan_id>/", views.subscribe_plan_view, name="subscribe"),
    path(
        "<int:subscription_id>/status/<str:target_status>/",
        views.subscription_change_status_view,
        name="change_status",
    ),
    path(
        "<int:subscription_id>/generate-invoice/",
        views.subscription_generate_invoice_view,
        name="generate_invoice",
    ),
]
