from django.contrib import admin
from .models import Download


@admin.register(Download)
class DownloadAdmin(admin.ModelAdmin):
    list_display = ['id', 'live_stream', 'quality', 'status', 'progress', 
                    'file_size_display', 'created_at', 'completed_at']
    list_filter = ['status', 'quality', 'created_at', 'completed_at']
    search_fields = ['live_stream__title', 'file_path', 'error_message']
    readonly_fields = ['created_at', 'updated_at', 'file_size_display']
    
    fieldsets = (
        ('기본 정보', {
            'fields': ('live_stream', 'quality', 'status')
        }),
        ('파일 정보', {
            'fields': ('file_path', 'file_size', 'file_size_display')
        }),
        ('진행 상태', {
            'fields': ('progress', 'download_speed', 'eta', 'task_id')
        }),
        ('시간 정보', {
            'fields': ('started_at', 'completed_at', 'created_at', 'updated_at')
        }),
        ('오류 정보', {
            'fields': ('retry_count', 'error_message'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['retry_download', 'cancel_download']
    
    def retry_download(self, request, queryset):
        """선택한 다운로드 재시도"""
        count = 0
        for download in queryset.filter(status__in=['failed', 'cancelled']):
            download.status = 'pending'
            download.error_message = None
            download.save()
            count += 1
        self.message_user(request, f'{count}개의 다운로드를 재시도 대기열에 추가했습니다.')
    retry_download.short_description = '다운로드 재시도'
    
    def cancel_download(self, request, queryset):
        """선택한 다운로드 취소"""
        count = queryset.filter(status__in=['pending', 'downloading']).update(status='cancelled')
        self.message_user(request, f'{count}개의 다운로드를 취소했습니다.')
    cancel_download.short_description = '다운로드 취소'