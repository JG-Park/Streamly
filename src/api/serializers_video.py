"""
YouTube 영상 추출 및 다운로드 시리얼라이저
"""

from rest_framework import serializers
from downloads.models_manual import ManualDownload


class VideoExtractSerializer(serializers.Serializer):
    """영상 정보 추출 요청 시리얼라이저"""
    url = serializers.URLField(required=True, help_text="YouTube 영상 URL")


class VideoDownloadSerializer(serializers.Serializer):
    """영상 다운로드 요청 시리얼라이저"""
    url = serializers.URLField(required=True)
    video_id = serializers.CharField(required=True)
    title = serializers.CharField(required=True)
    channel = serializers.CharField(required=False, allow_blank=True)
    duration = serializers.IntegerField(required=False, allow_null=True)
    thumbnail = serializers.URLField(required=False, allow_blank=True)
    
    download_type = serializers.ChoiceField(
        choices=['server', 'direct'],
        default='server',
        help_text="server: 서버에 저장, direct: CDN URL 반환"
    )
    
    quality = serializers.CharField(
        required=False,
        default='best',
        help_text="다운로드 품질 (best, worst, 또는 특정 format_id)"
    )
    
    format_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="특정 포맷 ID (direct 다운로드 시 사용)"
    )
    
    resolution = serializers.CharField(required=False, allow_blank=True)
    video_codec = serializers.CharField(required=False, allow_blank=True)
    audio_codec = serializers.CharField(required=False, allow_blank=True)


class ManualDownloadSerializer(serializers.ModelSerializer):
    """수동 다운로드 목록 시리얼라이저"""
    duration_display = serializers.ReadOnlyField()
    file_size_display = serializers.ReadOnlyField()
    requested_by_username = serializers.CharField(source='requested_by.username', read_only=True)
    
    class Meta:
        model = ManualDownload
        fields = [
            'id', 'url', 'video_id', 'title', 'channel_name',
            'duration', 'duration_display', 'thumbnail_url',
            'download_type', 'quality', 'status', 'progress',
            'file_size', 'file_size_display', 'resolution',
            'video_codec', 'audio_codec', 'direct_url',
            'direct_url_expires', 'drive_url', 'backup_status',
            'requested_by_username', 'created_at', 'completed_at'
        ]


class ManualDownloadDetailSerializer(serializers.ModelSerializer):
    """수동 다운로드 상세 시리얼라이저"""
    duration_display = serializers.ReadOnlyField()
    file_size_display = serializers.ReadOnlyField()
    requested_by_username = serializers.CharField(source='requested_by.username', read_only=True)
    
    class Meta:
        model = ManualDownload
        fields = '__all__'
        read_only_fields = [
            'video_id', 'created_at', 'updated_at', 'started_at',
            'completed_at', 'requested_by'
        ]