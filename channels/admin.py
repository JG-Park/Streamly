from django.contrib import admin
from django.utils.html import format_html
from .models import Channel, LiveStream


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'channel_id', 'is_active', 'last_checked', 
        'live_stream_count', 'created_at'
    ]
    list_filter = ['is_active', 'created_at', 'last_checked']
    search_fields = ['name', 'channel_id']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-is_active', 'name']
    
    def live_stream_count(self, obj):
        return obj.live_streams.count()
    live_stream_count.short_description = '라이브 스트림 수'


@admin.register(LiveStream)
class LiveStreamAdmin(admin.ModelAdmin):
    list_display = [
        'title_truncated', 'channel', 'status', 'started_at', 
        'ended_at', 'notification_sent', 'download_count'
    ]
    list_filter = ['status', 'notification_sent', 'channel', 'started_at']
    search_fields = ['title', 'video_id', 'channel__name']
    readonly_fields = ['created_at', 'updated_at', 'duration_display']
    date_hierarchy = 'started_at'
    ordering = ['-started_at']
    
    def title_truncated(self, obj):
        return obj.title[:50] + '...' if len(obj.title) > 50 else obj.title
    title_truncated.short_description = '제목'
    
    def download_count(self, obj):
        return obj.downloads.count()
    download_count.short_description = '다운로드 수'
    
    def duration_display(self, obj):
        duration = obj.duration
        if duration:
            hours, remainder = divmod(duration.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
        return "-"
    duration_display.short_description = '방송 시간'
