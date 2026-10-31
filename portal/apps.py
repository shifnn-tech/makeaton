"""
portal/apps.py
==============
Configuration for the BrightLoop unified portal app.
Connects signals in ready() for automated audit logging.
"""

from django.apps import AppConfig


class PortalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "portal"

    def ready(self):
        # Connect post_save and post_delete signals for audit logging
        import portal.signals  # noqa
