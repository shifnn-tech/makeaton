"""
portal/context_processors.py
============================
Context processor supplying notification badges and recent unread alerts
to all templates across the application.
"""


def notifications_context(request):
    """
    Supplies the logged-in user's unread notifications count and recent alerts
    for rendering the top navigation bar bell icon.
    """
    if getattr(request, "user", None) and request.user.is_authenticated:
        unread_notifications = request.user.notifications.filter(is_read=False)
        unread_count = unread_notifications.count()
        recent_unread = list(unread_notifications.order_by("-created_at")[:5])
        return {
            "unread_notifications_count": unread_count,
            "recent_unread_notifications": recent_unread,
        }
    return {
        "unread_notifications_count": 0,
        "recent_unread_notifications": [],
    }

