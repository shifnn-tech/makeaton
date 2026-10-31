"""
intelligence/urls.py
====================
Purpose:
    URL routes for the Revenue Intelligence module (Person 3).
"""

from django.urls import path
from . import views

app_name = "intelligence"

urlpatterns = [
    path("", views.revenue_dashboard_view, name="dashboard"),
    path("forecast/", views.forecast_health_view, name="forecast"),
]
