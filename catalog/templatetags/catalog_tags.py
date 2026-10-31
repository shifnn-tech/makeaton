"""
catalog/templatetags/catalog_tags.py
====================================
Custom template tags for catalog data retrieval inside templates.
Enables home.html to render active pricing plans dynamically without view changes.
"""

from django import template
from catalog.models import Plan

register = template.Library()


@register.simple_tag
def get_plans():
    """Returns all available subscription plans ordered by price."""
    try:
        return list(Plan.objects.all().order_by("price"))
    except Exception:
        return []
