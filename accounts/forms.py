"""
accounts/forms.py
=================
Purpose:
    Forms for user registration, authentication, and role assignment.
    Applies Bootstrap 5 form classes ('form-control') and enforces role rules.
"""

from django import forms
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class CustomerSignUpForm(forms.ModelForm):
    """
    Public signup form for new customers.
    Enforces customer role strictly: new signups are ALWAYS created with role='customer'.
    """

    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Jane"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Doe"}),
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "name@example.com"}),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Enter strong password"}),
        help_text="More than 8 characters, at least 1 uppercase, 1 lowercase, and 1 special character.",
    )
    confirm_password = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Re-enter password"}),
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "password")

    def clean_email(self):
        email = self.cleaned_data.get("email", "").lower().strip()
        if User.objects.filter(email=email).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password:
            if password != confirm_password:
                self.add_error("confirm_password", "Passwords do not match.")
            else:
                # Run through Django's configured password validators (including CustomComplexityValidator)
                validate_password(password)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        # CRITICAL SECURITY RULE: Public signups can only ever be customers
        user.role = User.ROLE_CUSTOMER
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    """
    Standard email + password login form styled with Bootstrap 5.
    Includes remember_me checkbox and accessible autocomplete attributes.
    """

    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "name@company.com",
            "autocomplete": "email",
            "autofocus": True,
            "id": "id_email",
        }),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your password",
            "autocomplete": "current-password",
            "id": "id_password",
        }),
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        label="Remember me",
        widget=forms.CheckboxInput(attrs={
            "class": "form-check-input",
            "id": "id_remember_me",
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email", "").lower().strip()
        password = cleaned_data.get("password")

        if email and password:
            self.user_cache = authenticate(email=email, password=password)
            if self.user_cache is None:
                raise ValidationError("Invalid email address or password. Please check and try again.")
            elif not self.user_cache.is_active:
                raise ValidationError("This account is currently inactive.")

        return cleaned_data

    def get_user(self):
        return getattr(self, "user_cache", None)


class StaffCreationForm(forms.ModelForm):
    """
    Admin-only form to create internal staff members.
    Only users with role='admin' should be permitted to submit this form.
    """

    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        help_text="More than 8 characters with upper, lower, and special symbols.",
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "password")

    def clean_email(self):
        email = self.cleaned_data.get("email", "").lower().strip()
        if User.objects.filter(email=email).exists():
            raise ValidationError("A user with this email address already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            validate_password(password)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.ROLE_STAFF
        user.is_staff = True  # Allows access to Django admin if needed
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user
