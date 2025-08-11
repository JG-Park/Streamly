from django.contrib import admin
from django.utils.html import format_html
from .models import Settings, SystemLog


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ['key', 'value_display', 'value_type', 'description_short', 'updated_at']
    list_filter = ['value_type', 'updated_at']
    search_fields = ['key', 'description']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['key']
    
    def value_display(self, obj):
        value = obj.value
        if len(value) > 50:
            return value[:50] + '...'
        return value
    value_display.short_description = '값'
    
    def description_short(self, obj):
        if obj.description and len(obj.description) > 50:
            return obj.description[:50] + '...'
        return obj.description or '-'
    description_short.short_description = '설명'


@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = ['level_colored', 'category', 'message_short', 'created_at']
    list_filter = ['level', 'category', 'created_at']
    search_fields = ['message']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    def level_colored(self, obj):
        colors = {
            'DEBUG': 'gray',
            'INFO': 'blue',
            'WARNING': 'orange',
            'ERROR': 'red',
            'CRITICAL': 'darkred',
        }
        color = colors.get(obj.level, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.level
        )
    level_colored.short_description = '레벨'
    
    def message_short(self, obj):
        return obj.message[:100] + '...' if len(obj.message) > 100 else obj.message
    message_short.short_description = '메시지'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
