from django.contrib import admin

from .models import OAuthConnection


@admin.register(OAuthConnection)
class OAuthConnectionAdmin(admin.ModelAdmin):
    list_display = ("user", "provider_key", "provider_user_id", "created_at")
    search_fields = (
        "user__email",
        "provider_user_id",
    )
    list_filter = ("provider_key",)
