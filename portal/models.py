"""
portal/models.py
================
Data models for user notifications and system-wide audit logging.

Models:
  1. Notification: Stores alerts and reminders for users (e.g. upcoming/overdue invoices).
  2. AuditLog: Tracks creations, updates, and deletions across key business models
     (Subscription, Invoice, Payment, Discount).
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    """
    Notification model:
    Represents an in-app alert or reminder directed to a specific user.
    Includes a direct link for quick navigation and a read/unread status flag.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        help_text=_("The user who receives this notification."),
    )
    message = models.CharField(
        max_length=255,
        help_text=_("Brief description of the notification event."),
    )
    link = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Internal URL path to navigate to when clicked."),
    )
    is_read = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_("True if the user has viewed or dismissed this alert."),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text=_("Timestamp when this notification was generated."),
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")

    def __str__(self):
        status = "Read" if self.is_read else "Unread"
        return f"[{status}] {self.user.email}: {self.message}"


class AuditLog(models.Model):
    """
    AuditLog model:
    Records an immutable audit trail whenever critical domain records
    (Subscription, Invoice, Payment, Discount) are created, modified, or deleted.
    """

    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"

    ACTION_CHOICES = (
        (ACTION_CREATE, _("Created")),
        (ACTION_UPDATE, _("Updated")),
        (ACTION_DELETE, _("Deleted")),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text=_("User who performed the action, or None if automated by system."),
    )
    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES,
        default=ACTION_CREATE,
        help_text=_("Action performed: create, update, or delete."),
    )
    model_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text=_("Name of the affected model (e.g. Subscription, Invoice)."),
    )
    object_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=_("Identifier of the affected record."),
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text=_("Human-readable explanation of what changed."),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text=_("Timestamp when the action was performed."),
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Audit Log")
        verbose_name_plural = _("Audit Logs")

    def __str__(self):
        user_display = self.user.email if self.user else "System"
        return f"{self.get_action_display()} {self.model_name} #{self.object_id} by {user_display}"
