from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User


class ManualDownload(models.Model):
    """수동 URL 다운로드 모델"""
    
    STATUS_CHOICES = [
        ('pending', '대기 중'),
        ('extracting', '정보 추출 중'),
        ('downloading', '다운로드 중'),
        ('completed', '완료'),
        ('failed', '실패'),
    ]
    
    DOWNLOAD_TYPE_CHOICES = [
        ('server', '서버 저장'),
        ('direct', 'CDN 다이렉트'),
    ]
    
    # 기본 정보
    url = models.URLField(
        max_length=500,
        help_text="YouTube 영상 URL"
    )
    video_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="YouTube 비디오 ID"
    )
    title = models.CharField(
        max_length=500,
        blank=True,
        null=True
    )
    channel_name = models.CharField(
        max_length=200,
        blank=True,
        null=True
    )
    duration = models.IntegerField(
        null=True,
        blank=True,
        help_text="영상 길이 (초)"
    )
    thumbnail_url = models.URLField(
        max_length=500,
        blank=True,
        null=True
    )
    
    # 다운로드 설정
    download_type = models.CharField(
        max_length=10,
        choices=DOWNLOAD_TYPE_CHOICES,
        default='server'
    )
    quality = models.CharField(
        max_length=10,
        default='best',
        help_text="다운로드 품질 설정"
    )
    
    # 서버 저장 관련
    file_path = models.CharField(
        max_length=500,
        blank=True,
        null=True
    )
    file_size = models.BigIntegerField(
        default=0,
        help_text="파일 크기 (바이트)"
    )
    
    # CDN 다이렉트 관련
    direct_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        help_text="CDN 다이렉트 URL"
    )
    direct_url_expires = models.DateTimeField(
        blank=True,
        null=True,
        help_text="다이렉트 URL 만료 시간"
    )
    
    # 영상 정보
    resolution = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="해상도 (예: 1920x1080)"
    )
    video_codec = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )
    audio_codec = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )
    fps = models.IntegerField(
        null=True,
        blank=True
    )
    
    # 상태 관리
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    progress = models.IntegerField(
        default=0,
        help_text="다운로드 진행률 (0-100)"
    )
    error_message = models.TextField(
        blank=True,
        null=True
    )
    
    # Google Drive 백업
    drive_url = models.URLField(
        max_length=500,
        blank=True,
        null=True
    )
    backup_status = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        choices=[
            ('pending', '대기중'),
            ('uploading', '업로드중'),
            ('completed', '완료'),
            ('failed', '실패'),
        ]
    )
    
    # 사용자 정보
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manual_downloads'
    )
    
    # 시간 정보
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(
        blank=True,
        null=True
    )
    completed_at = models.DateTimeField(
        blank=True,
        null=True
    )
    
    class Meta:
        verbose_name = "수동 다운로드"
        verbose_name_plural = "수동 다운로드들"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['video_id']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"{self.title or self.url} - {self.get_status_display()}"
    
    @property
    def duration_display(self):
        """영상 길이 표시용 문자열"""
        if not self.duration:
            return "00:00"
        
        hours = self.duration // 3600
        minutes = (self.duration % 3600) // 60
        seconds = self.duration % 60
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    
    @property
    def file_size_display(self):
        """파일 크기 표시용 문자열"""
        if self.file_size == 0:
            return "0B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        import math
        i = int(math.floor(math.log(self.file_size, 1024)))
        p = math.pow(1024, i)
        s = round(self.file_size / p, 2)
        return f"{s} {size_names[i]}"
    
    def extract_info(self):
        """영상 정보 추출"""
        self.status = 'extracting'
        self.save(update_fields=['status'])
    
    def start_download(self):
        """다운로드 시작"""
        self.status = 'downloading'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])
    
    def complete_download(self, **kwargs):
        """다운로드 완료"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.progress = 100
        
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        
        self.save()
    
    def fail_download(self, error_message=None):
        """다운로드 실패"""
        self.status = 'failed'
        if error_message:
            self.error_message = error_message
        self.save(update_fields=['status', 'error_message'])