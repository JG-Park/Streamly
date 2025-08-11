from django.db import models
from django.utils import timezone
from django.core.validators import URLValidator


class Channel(models.Model):
    """YouTube 채널 정보"""
    channel_id = models.CharField(
        max_length=50, 
        unique=True, 
        help_text="YouTube 채널 ID (예: UC...)"
    )
    name = models.CharField(
        max_length=200, 
        help_text="채널 이름"
    )
    url = models.URLField(
        validators=[URLValidator()],
        help_text="채널 URL"
    )
    is_active = models.BooleanField(
        default=True, 
        help_text="모니터링 활성화 여부"
    )
    last_checked = models.DateTimeField(
        null=True, 
        blank=True, 
        help_text="마지막 확인 시간"
    )
    check_interval_minutes = models.IntegerField(
        default=5,
        help_text="체크 주기 (분). 채널 활동에 따라 자동 조정됨"
    )
    last_live_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="마지막 라이브 시간"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "YouTube 채널"
        verbose_name_plural = "YouTube 채널들"
        ordering = ['-is_active', 'name']
        
    def __str__(self):
        return f"{self.name} ({self.channel_id})"
    
    def update_last_checked(self):
        """마지막 확인 시간 업데이트"""
        self.last_checked = timezone.now()
        self.save(update_fields=['last_checked'])
    
    def update_check_interval(self, live_history_count: int = 0):
        """채널 활동에 따라 체크 주기 자동 조정"""
        if live_history_count >= 7:  # 주 7회 이상
            self.check_interval_minutes = 1
        elif live_history_count >= 3:  # 주 3-6회
            self.check_interval_minutes = 5
        else:  # 주 3회 미만
            self.check_interval_minutes = 15
        self.save(update_fields=['check_interval_minutes'])


class LiveStream(models.Model):
    """라이브 스트림 기록"""
    STATUS_CHOICES = [
        ('live', '라이브 중'),
        ('ended', '종료됨'),
        ('downloading', '다운로드 중'),
        ('completed', '완료'),
        ('failed', '실패'),
    ]
    
    channel = models.ForeignKey(
        Channel, 
        on_delete=models.CASCADE, 
        related_name='live_streams'
    )
    video_id = models.CharField(
        max_length=50, 
        unique=True, 
        help_text="YouTube 비디오 ID"
    )
    title = models.CharField(
        max_length=500, 
        help_text="라이브 스트림 제목"
    )
    url = models.URLField(
        help_text="라이브 스트림 URL"
    )
    thumbnail_url = models.URLField(
        blank=True, 
        null=True,
        help_text="썸네일 URL"
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='live'
    )
    started_at = models.DateTimeField(
        default=timezone.now,
        help_text="라이브 시작 시간"
    )
    ended_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="라이브 종료 시간"
    )
    notification_sent = models.BooleanField(
        default=False,
        help_text="알림 발송 여부"
    )
    # 재시도 관련 필드
    retry_count = models.IntegerField(
        default=0,
        help_text="다운로드 재시도 횟수"
    )
    last_retry_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="마지막 재시도 시간"
    )
    retry_enabled = models.BooleanField(
        default=True,
        help_text="재시도 활성화 여부"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "라이브 스트림"
        verbose_name_plural = "라이브 스트림들"
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['video_id']),
            models.Index(fields=['channel', 'status']),
            models.Index(fields=['-started_at']),
        ]
        
    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"
    
    @property
    def duration(self):
        """라이브 방송 시간"""
        if self.ended_at:
            return self.ended_at - self.started_at
        return None
    
    def mark_as_ended(self):
        """라이브 종료 처리"""
        self.status = 'ended'
        self.ended_at = timezone.now()
        self.save(update_fields=['status', 'ended_at'])
