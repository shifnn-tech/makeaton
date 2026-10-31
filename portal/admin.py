"""
portal/admin.py
---------------
Registers the Notification and AuditLog models so they appear in
the Django admin panel at /admin/. Beginners can then see, search
and filter all notifications and audit-log entries from the browser.
"""

from django.contrib import admin

from .models import AuditLog, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Admin view for Notification — shows who got what and whether it was read."""

    list_display = ["user", "message", "is_read", "created_at"]
    list_filter = ["is_read", "created_at"]
    search_fields = ["user__email", "message"]
    ordering = ["-created_at"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Admin view for AuditLog — shows every create/update/delete event."""

    list_display = ["action", "model_name", "object_id", "user", "created_at"]
    list_filter = ["action", "model_name", "created_at"]
    search_fields = ["user__email", "description"]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]
