from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Settings(models.Model):
    """시스템 설정"""
    SETTING_TYPES = [
        ('integer', '정수'),
        ('string', '문자열'),
        ('boolean', '불린'),
        ('float', '실수'),
    ]
    
    key = models.CharField(
        max_length=100, 
        unique=True,
        help_text="설정 키"
    )
    value = models.TextField(
        help_text="설정 값"
    )
    value_type = models.CharField(
        max_length=20, 
        choices=SETTING_TYPES, 
        default='string'
    )
    description = models.TextField(
        blank=True, 
        null=True,
        help_text="설정 설명"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "설정"
        verbose_name_plural = "설정들"
        ordering = ['key']
        
    def __str__(self):
        return f"{self.key}: {self.value}"
    
    def get_typed_value(self):
        """타입에 맞게 변환된 값 반환"""
        if self.value_type == 'integer':
            return int(self.value)
        elif self.value_type == 'float':
            return float(self.value)
        elif self.value_type == 'boolean':
            return self.value.lower() in ('true', '1', 'yes', 'on')
        return self.value
    
    @classmethod
    def get_setting(cls, key, default=None):
        """설정 값 가져오기"""
        try:
            setting = cls.objects.get(key=key)
            return setting.get_typed_value()
        except cls.DoesNotExist:
            return default
    
    @classmethod
    def set_setting(cls, key, value, value_type='string', description=None):
        """설정 값 저장하기"""
        setting, created = cls.objects.get_or_create(
            key=key,
            defaults={
                'value': str(value),
                'value_type': value_type,
                'description': description or f"{key} 설정"
            }
        )
        if not created:
            setting.value = str(value)
            setting.value_type = value_type
            if description:
                setting.description = description
            setting.save()
        return setting


class SystemLog(models.Model):
    """시스템 로그"""
    LEVEL_CHOICES = [
        ('DEBUG', 'Debug'),
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical'),
    ]
    
    CATEGORY_CHOICES = [
        ('system', '시스템'),
        ('channel_check', '채널 체크'),
        ('download', '다운로드'),
        ('notification', '알림'),
        ('cleanup', '정리'),
    ]
    
    level = models.CharField(
        max_length=10, 
        choices=LEVEL_CHOICES, 
        default='INFO'
    )
    category = models.CharField(
        max_length=20, 
        choices=CATEGORY_CHOICES, 
        default='system'
    )
    message = models.TextField(
        help_text="로그 메시지"
    )
    data = models.JSONField(
        blank=True, 
        null=True,
        help_text="추가 데이터 (JSON)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "시스템 로그"
        verbose_name_plural = "시스템 로그들"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['level']),
            models.Index(fields=['category']),
            models.Index(fields=['-created_at']),
        ]
        
    def __str__(self):
        return f"[{self.level}] {self.category}: {self.message[:50]}..."
    
    @classmethod
    def log(cls, level, category, message, data=None):
        """로그 생성"""
        return cls.objects.create(
            level=level,
            category=category,
            message=message,
            data=data
        )
