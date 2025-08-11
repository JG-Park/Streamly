from django.db import models
from django.utils import timezone
from channels.models import LiveStream


class Download(models.Model):
    """다운로드 작업 모델"""
    
    STATUS_CHOICES = [
        ('pending', '대기 중'),
        ('downloading', '다운로드 중'),
        ('completed', '완료'),
        ('failed', '실패'),
        ('cancelled', '취소됨'),
    ]
    
    QUALITY_CHOICES = [
        ('best', '고화질'),
        ('worst', '저화질'),
    ]
    
    live_stream = models.ForeignKey(
        LiveStream,
        on_delete=models.CASCADE,
        related_name='downloads'
    )
    quality = models.CharField(
        max_length=10,
        choices=QUALITY_CHOICES,
        default='best'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    file_path = models.CharField(
        max_length=500,
        blank=True,
        null=True
    )
    file_size = models.BigIntegerField(
        default=0,
        help_text="파일 크기 (바이트)"
    )
    progress = models.IntegerField(
        default=0,
        help_text="다운로드 진행률 (0-100)"
    )
    download_speed = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="다운로드 속도"
    )
    eta = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="예상 완료 시간"
    )
    error_message = models.TextField(
        blank=True,
        null=True
    )
    task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Celery 태스크 ID"
    )
    started_at = models.DateTimeField(
        blank=True,
        null=True
    )
    completed_at = models.DateTimeField(
        blank=True,
        null=True
    )
    retry_count = models.IntegerField(
        default=0,
        help_text="재시도 횟수"
    )
    delete_after = models.DateTimeField(
        blank=True,
        null=True,
        help_text="자동 삭제 예정 시간"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "다운로드"
        verbose_name_plural = "다운로드들"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'quality']),
            models.Index(fields=['live_stream', 'quality']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"{self.live_stream.title} - {self.get_quality_display()}"
    
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
    
    @property
    def duration(self):
        """다운로드 소요 시간"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None
    
    @property
    def download_duration(self):
        """다운로드 소요 시간 (별칭)"""
        return self.duration
    
    @property
    def file_exists(self):
        """파일 존재 여부"""
        if self.file_path:
            import os
            return os.path.exists(self.file_path)
        return False
    
    def start_download(self):
        """다운로드 시작"""
        self.status = 'downloading'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])
    
    def complete_download(self, file_path=None, file_size=None):
        """다운로드 완료"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.progress = 100
        if file_path:
            self.file_path = file_path
        if file_size:
            self.file_size = file_size
        self.save(update_fields=['status', 'completed_at', 'progress', 'file_path', 'file_size'])
    
    def fail_download(self, error_message=None):
        """다운로드 실패"""
        self.status = 'failed'
        if error_message:
            self.error_message = error_message
        self.save(update_fields=['status', 'error_message'])
    
    def cancel_download(self):
        """다운로드 취소"""
        self.status = 'cancelled'
        self.save(update_fields=['status'])
    
    def update_progress(self, progress, speed=None, eta=None):
        """진행률 업데이트"""
        self.progress = min(100, max(0, progress))
        if speed:
            self.download_speed = speed
        if eta:
            self.eta = eta
        self.save(update_fields=['progress', 'download_speed', 'eta'])
    
    def delete_file(self):
        """다운로드 파일 삭제"""
        if self.file_path and self.file_exists:
            import os
            try:
                os.remove(self.file_path)
                # 관련 파일들도 삭제 (썸네일, 정보 파일 등)
                base_path = os.path.splitext(self.file_path)[0]
                for ext in ['.info.json', '.description', '.jpg', '.png', '.webp']:
                    related_file = base_path + ext
                    if os.path.exists(related_file):
                        os.remove(related_file)
                return True
            except OSError:
                return False
        return False
    
    # tasks.py에서 사용하는 메서드 별칭
    def mark_as_downloading(self):
        """다운로드 시작 (별칭)"""
        return self.start_download()
    
    def mark_as_completed(self, file_path=None, file_size=None):
        """다운로드 완료 (별칭)"""
        return self.complete_download(file_path, file_size)
    
    def mark_as_failed(self, error_message=None):
        """다운로드 실패 (별칭)"""
        return self.fail_download(error_message)