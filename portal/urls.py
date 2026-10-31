"""
portal/urls.py
==============
URL routes for the unified Portal application:
  - Role-based landing redirect after login
  - Admin, Staff, and Customer dashboards
  - Global cross-model search (?q=)
  - 30-day billing calendar and upcoming renewal schedule
  - Staff-only customer directory and detailed customer profiles
  - Activity audit timeline (admin & staff)
  - In-app notification center and mark-as-read actions
  - Compliance reports & CSV export (admin & staff)
"""

from django.urls import path
from . import views

app_name = "portal"

urlpatterns = [
    # 1. Role-based landing view
    path("", views.landing_view, name="landing"),

    # 2. Admin dashboard
    path("admin-dashboard/", views.admin_dashboard_view, name="admin_dashboard"),

    # 3. Staff dashboard
    path("staff-dashboard/", views.staff_dashboard_view, name="staff_dashboard"),

    # 4. Customer dashboard
    path("customer-dashboard/", views.customer_dashboard_view, name="customer_dashboard"),

    # 5. Global search
    path("search/", views.search_view, name="search"),

    # 6. Billing calendar & upcoming renewals
    path("calendar/", views.billing_calendar_view, name="calendar"),

    # 7. Staff-only customer list and customer detail
    path("customers/", views.customer_list_view, name="customer_list"),
    path("customers/<int:customer_id>/", views.customer_detail_view, name="customer_detail"),

    # 8. Activity Timeline / Audit Trail (admin & staff)
    path("activity/", views.activity_timeline_view, name="activity_timeline"),

    # 9. In-app Notifications
    path("notifications/", views.notification_list_view, name="notifications"),
    path("notifications/<int:notification_id>/read/", views.notification_mark_read_view, name="notification_read"),
    path("notifications/mark-all-read/", views.notification_mark_all_read_view, name="notification_mark_all_read"),

    # 10. Reports & CSV Export (admin & staff)
    path("reports/", views.reports_view, name="reports"),
]
