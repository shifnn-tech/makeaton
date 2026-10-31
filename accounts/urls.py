"""
accounts/urls.py
================
Purpose:
    URL configuration for user authentication, registration, password resets,
    and staff management.
"""

from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

app_name = "accounts"

urlpatterns = [
    # Landing / Home
    path("", views.home_view, name="home"),

    # Authentication (Customer & Staff/Admin portals)
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("login/staff/", views.login_view, {"portal": "staff"}, name="login_staff"),
    path("logout/", views.logout_view, name="logout"),

    # Admin: Create staff user
    path("staff/create/", views.staff_create_view, name="staff_create"),

    # Django built-in password reset flow with custom Bootstrap templates
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/password_reset_email.html",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset-confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
]
