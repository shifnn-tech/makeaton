"""
portal/signals.py
=================
Signals to automatically log creations, updates, and deletions for key business models:
  - Subscription (subscriptions.models)
  - Invoice (billing.models)
  - Payment (billing.models)
  - Discount (catalog.models)

Every post_save and post_delete event generates an immutable AuditLog entry.
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from subscriptions.models import Subscription
from billing.models import Invoice, Payment
from catalog.models import Discount
from .models import AuditLog


@receiver(post_save, sender=Subscription)
@receiver(post_save, sender=Invoice)
@receiver(post_save, sender=Payment)
@receiver(post_save, sender=Discount)
def log_model_save(sender, instance, created, **kwargs):
    """
    Signal handler: Triggered whenever a Subscription, Invoice, Payment, or Discount is saved.
    Creates an AuditLog entry with action='create' if newly created, or 'update' if modified.
    """
    action = AuditLog.ACTION_CREATE if created else AuditLog.ACTION_UPDATE
    model_name = sender.__name__
    object_id = str(getattr(instance, "pk", "") or "")

    # Check for actor explicitly attached to instance, or fallback to associated user
    user = getattr(instance, "_actor", None)
    if not user and hasattr(instance, "user") and instance.user:
        user = instance.user

    # Human-readable descriptive summary
    if model_name == "Subscription":
        plan_name = instance.plan.name if getattr(instance, "plan", None) else "No Plan"
        desc = (
            f"{'Created' if created else 'Updated'} Subscription {getattr(instance, 'number', object_id)} "
            f"({plan_name}) with status '{getattr(instance, 'status', '')}'"
        )
    elif model_name == "Invoice":
        total_val = getattr(instance, "total", "0.00")
        desc = (
            f"{'Created' if created else 'Updated'} Invoice {getattr(instance, 'number', object_id)} "
            f"for ${total_val} with status '{getattr(instance, 'status', '')}'"
        )
    elif model_name == "Payment":
        amount_val = getattr(instance, "amount", "0.00")
        inv_num = instance.invoice.number if getattr(instance, "invoice", None) else "N/A"
        desc = (
            f"{'Created' if created else 'Updated'} Payment #{object_id} of ${amount_val} "
            f"({getattr(instance, 'method', '')}) for Invoice {inv_num}"
        )
    elif model_name == "Discount":
        desc = (
            f"{'Created' if created else 'Updated'} Discount '{getattr(instance, 'name', object_id)}' "
            f"({getattr(instance, 'value', '')} {getattr(instance, 'type', '')})"
        )
    else:
        desc = f"{'Created' if created else 'Updated'} {model_name} #{object_id}"

    AuditLog.objects.create(
        user=user,
        action=action,
        model_name=model_name,
        object_id=object_id,
        description=desc,
    )


@receiver(post_delete, sender=Subscription)
@receiver(post_delete, sender=Invoice)
@receiver(post_delete, sender=Payment)
@receiver(post_delete, sender=Discount)
def log_model_delete(sender, instance, **kwargs):
    """
    Signal handler: Triggered whenever a Subscription, Invoice, Payment, or Discount is deleted.
    Creates an AuditLog entry with action='delete'.
    """
    model_name = sender.__name__
    object_id = str(getattr(instance, "pk", "") or "")
    user = getattr(instance, "_actor", None)
    if not user and hasattr(instance, "user") and instance.user:
        user = instance.user

    if hasattr(instance, "number"):
        ref = getattr(instance, "number")
    elif hasattr(instance, "name"):
        ref = getattr(instance, "name")
    else:
        ref = f"#{object_id}"

    desc = f"Deleted {model_name} {ref}"

    AuditLog.objects.create(
        user=user,
        action=AuditLog.ACTION_DELETE,
        model_name=model_name,
        object_id=object_id,
        description=desc,
    )

