"""
brightloop/settings.py
======================
Purpose:
    Core configuration for the BrightLoop Subscription Management System.
    Includes database, installed apps, password validation, authentication backend,
    static file mappings, and role-based redirect settings.
"""

import os
from pathlib import Path

# Base directory: points to the root directory containing manage.py
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-%8o$2*)2*@q#ji5c=rd#qehc(=61!009dd+x73#yx2+v72&r&m"
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    # BrightLoop Apps (Kept modular so team members can work in parallel)
    "accounts.apps.AccountsConfig",
    "catalog.apps.CatalogConfig",
    "subscriptions.apps.SubscriptionsConfig",
    "billing.apps.BillingConfig",
    "dashboard.apps.DashboardConfig",
    "intelligence.apps.IntelligenceConfig",
    "portal.apps.PortalConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "brightloop.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "portal.context_processors.notifications_context",
            ],
        },
    },
]

WSGI_APPLICATION = "brightloop.wsgi.application"

# Database: SQLite for lightweight hackathon setup with zero external dependencies
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Custom User Model
AUTH_USER_MODEL = "accounts.User"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    # Custom project rule: >8 chars, at least 1 uppercase, 1 lowercase, 1 special character
    {
        "NAME": "accounts.validators.CustomComplexityValidator",
    },
]

# Authentication URLs
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "portal:landing"
LOGOUT_REDIRECT_URL = "accounts:login"

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# Stored locally in static/ (Bootstrap 5 bundle included for 100% offline development)
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ==============================================================================
# Email Configuration
# ==============================================================================
# Default: Console Email Backend
# During local development and hackathons, password reset emails will print
# directly into your terminal console without requiring an internet connection.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
