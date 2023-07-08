from django.contrib import admin

from .models import Flag, FlagResult


@admin.register(Flag)
class FlagAdmin(admin.ModelAdmin):
    list_display = ["name", "enabled", "created_at", "used_at", "uuid"]
    search_fields = ["name", "description"]


@admin.register(FlagResult)
class FlagResultAdmin(admin.ModelAdmin):
    list_display = ["flag", "key", "value", "created_at", "updated_at", "uuid"]
    search_fields = ["flag__name", "key"]
    list_filter = ["flag", "key"]
    list_select_related = ["flag"]
