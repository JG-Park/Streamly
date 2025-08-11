"""
API 시리얼라이저들
"""

from rest_framework import serializers
from channels.models import Channel, LiveStream
from core.models import Settings, SystemLog

# downloads.models는 나중에 임포트 (순환 임포트 방지)
try:
    from downloads.models import Download
except ImportError:
    # 마이그레이션 중일 때는 임포트 실패 허용
    Download = None


class ChannelSerializer(serializers.ModelSerializer):
    """채널 시리얼라이저"""
    live_stream_count = serializers.SerializerMethodField()
    last_live_stream = serializers.SerializerMethodField()
    
    class Meta:
        model = Channel
        fields = [
            'id', 'channel_id', 'name', 'url', 'is_active',
            'last_checked', 'created_at', 'updated_at',
            'live_stream_count', 'last_live_stream'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_checked']
    
    def get_live_stream_count(self, obj):
        return obj.live_streams.count()
    
    def get_last_live_stream(self, obj):
        last_stream = obj.live_streams.first()  # ordering by -started_at
        if last_stream:
            return {
                'id': last_stream.id,
                'title': last_stream.title,
                'started_at': last_stream.started_at,
                'status': last_stream.status
            }
        return None


class ChannelCreateSerializer(serializers.Serializer):
    """채널 생성 시리얼라이저"""
    url = serializers.URLField(
        help_text="YouTube 채널 URL (예: https://www.youtube.com/@channelname)"
    )
    
    def validate_url(self, value):
        """URL 유효성 검사"""
        if 'youtube.com' not in value:
            raise serializers.ValidationError("YouTube 채널 URL이 아닙니다.")
        return value


class LiveStreamSerializer(serializers.ModelSerializer):
    """라이브 스트림 시리얼라이저"""
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    duration_formatted = serializers.SerializerMethodField()
    download_count = serializers.SerializerMethodField()
    
    class Meta:
        model = LiveStream
        fields = [
            'id', 'video_id', 'title', 'url', 'thumbnail_url',
            'status', 'started_at', 'ended_at', 'notification_sent',
            'created_at', 'updated_at', 'channel_name',
            'duration_formatted', 'download_count'
        ]
        read_only_fields = [
            'id', 'video_id', 'created_at', 'updated_at',
            'channel_name', 'duration_formatted', 'download_count'
        ]
    
    def get_duration_formatted(self, obj):
        duration = obj.duration
        if duration:
            hours, remainder = divmod(duration.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
        return None
    
    def get_download_count(self, obj):
        return obj.downloads.count()


class DownloadSerializer(serializers.ModelSerializer):
    """다운로드 시리얼라이저"""
    live_stream_title = serializers.CharField(source='live_stream.title', read_only=True)
    channel_name = serializers.CharField(source='live_stream.channel.name', read_only=True)
    file_size_formatted = serializers.SerializerMethodField()
    file_exists = serializers.BooleanField(read_only=True)
    download_duration_formatted = serializers.SerializerMethodField()
    
    class Meta:
        @property
        def model(self):
            if Download is None:
                from downloads.models import Download
            return Download
        
        model = Download if Download is not None else None
        fields = [
            'id', 'quality', 'status', 'file_path', 'file_size',
            'started_at', 'completed_at', 'delete_after',
            'error_message', 'created_at', 'updated_at',
            'live_stream_title', 'channel_name', 'file_size_formatted',
            'file_exists', 'download_duration_formatted', 'progress',
            'download_speed', 'eta', 'retry_count'
        ]
        read_only_fields = [
            'id', 'file_path', 'file_size', 'started_at',
            'completed_at', 'error_message', 'created_at', 'updated_at',
            'live_stream_title', 'channel_name', 'file_size_formatted',
            'file_exists', 'download_duration_formatted', 'progress',
            'download_speed', 'eta', 'retry_count'
        ]
    
    def get_file_size_formatted(self, obj):
        if obj.file_size:
            from core.utils import format_file_size
            return format_file_size(obj.file_size)
        return None
    
    def get_download_duration_formatted(self, obj):
        duration = obj.download_duration
        if duration:
            total_seconds = int(duration.total_seconds())
            minutes, seconds = divmod(total_seconds, 60)
            return f"{minutes:02d}:{seconds:02d}"
        return None


class SettingsSerializer(serializers.ModelSerializer):
    """설정 시리얼라이저"""
    typed_value = serializers.SerializerMethodField()
    
    class Meta:
        model = Settings
        fields = [
            'id', 'key', 'value', 'value_type', 'description',
            'created_at', 'updated_at', 'typed_value'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'typed_value']
    
    def get_typed_value(self, obj):
        return obj.get_typed_value()


class SystemLogSerializer(serializers.ModelSerializer):
    """시스템 로그 시리얼라이저"""
    
    class Meta:
        model = SystemLog
        fields = [
            'id', 'level', 'category', 'message', 'data', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class DashboardStatsSerializer(serializers.Serializer):
    """대시보드 통계 시리얼라이저"""
    total_channels = serializers.IntegerField()
    active_channels = serializers.IntegerField()
    total_live_streams = serializers.IntegerField()
    current_live_count = serializers.IntegerField()
    total_downloads = serializers.IntegerField()
    completed_downloads = serializers.IntegerField()
    pending_downloads = serializers.IntegerField()
    failed_downloads = serializers.IntegerField()
    total_storage_used = serializers.CharField()
    recent_activities = serializers.ListField()


class TelegramTestSerializer(serializers.Serializer):
    """텔레그램 테스트 시리얼라이저"""
    message = serializers.CharField(
        max_length=1000,
        default="🤖 Streamly 테스트 메시지입니다!"
    )