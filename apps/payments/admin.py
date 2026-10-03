from django.contrib import admin

from apps.payments.models import WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only view so a human can see which payments need a refund."""

    list_display = ("provider_event_id", "event_type", "status", "detail", "received_at")
    list_filter = ("status", "event_type")
    search_fields = ("provider_event_id", "detail")
    readonly_fields = tuple(f.name for f in WebhookEvent._meta.fields)

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False
