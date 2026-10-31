"""
accounts/views.py
=================
Purpose:
    Authentication and role-based dashboard views.
    Handles signup (customers only), login, logout, role-based landing page,
    and admin-restricted staff creation.
"""

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import CustomerSignUpForm, LoginForm, StaffCreationForm
from .decorators import role_required


def home_view(request):
    """
    Root / Home landing page.
    Renders different contextual summaries depending on whether the visitor
    is anonymous, a customer, staff, or admin.
    """
    context = {
        "user": request.user,
    }
    return render(request, "home.html", context)


def signup_view(request):
    """
    Public registration view.
    Always assigns role='customer' to ensure external signups have restricted access.
    """
    if request.user.is_authenticated:
        return redirect("accounts:home")

    if request.method == "POST":
        form = CustomerSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(
                request,
                f"Account created successfully for {user.email}! Please log in below."
            )
            return redirect("accounts:login")
    else:
        form = CustomerSignUpForm()

    return render(request, "accounts/signup.html", {"form": form})


def login_view(request):
    """
    Custom login view using email and password.
    Redirects to the 'next' parameter if present, or to the home dashboard.
    Respects 'remember_me': sets session expiry accordingly.
    """
    if request.user.is_authenticated:
        return redirect("accounts:home")

    next_url = request.GET.get("next") or request.POST.get("next") or "accounts:home"

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)

            remember_me = form.cleaned_data.get("remember_me", True)
            if not remember_me:
                request.session.set_expiry(0)  # Expires when browser closes
            else:
                request.session.set_expiry(1209600)  # 2 weeks persistent session

            messages.success(request, f"Welcome back, {user.first_name or user.email}!")
            return redirect(next_url)
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form, "next": next_url})


def logout_view(request):
    """
    Logs out the current user and redirects to login page with feedback.
    Supports both POST (recommended by Django 5+) and GET for convenience.
    """
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "You have been successfully logged out.")
    return redirect("accounts:login")


@role_required("admin")
def staff_create_view(request):
    """
    Admin-only view: Only system administrators can create staff user accounts.
    Enforces the rule: 'Only admin can create staff users'.
    """
    if request.method == "POST":
        form = StaffCreationForm(request.POST)
        if form.is_valid():
            staff_user = form.save()
            messages.success(
                request,
                f"Staff member {staff_user.email} was successfully created!"
            )
            return redirect("accounts:home")
    else:
        form = StaffCreationForm()

    return render(request, "accounts/staff_create.html", {"form": form})
