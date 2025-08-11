"""
채널 관리 폼들
"""

from django import forms
from django.core.exceptions import ValidationError
from .models import Channel
from core.utils import YouTubeExtractor
import logging

logger = logging.getLogger('streamly')


class ChannelAddForm(forms.ModelForm):
    """YouTube URL을 통한 채널 추가 폼"""
    
    youtube_url = forms.URLField(
        label="YouTube URL",
        help_text="YouTube 채널 URL을 입력하세요 (예: https://www.youtube.com/@channelname)",
        widget=forms.URLInput(attrs={
            'class': 'input input-bordered w-full',
            'placeholder': 'https://www.youtube.com/@channelname'
        })
    )
    
    class Meta:
        model = Channel
        fields = ['youtube_url', 'is_active']
        widgets = {
            'is_active': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary'})
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['is_active'].initial = True
        
    def clean_youtube_url(self):
        """YouTube URL 유효성 검사 및 채널 정보 추출"""
        url = self.cleaned_data.get('youtube_url')
        
        if not url:
            raise ValidationError("YouTube URL을 입력해주세요.")
        
        # YouTube URL 형식 검사
        youtube_patterns = [
            'youtube.com/channel/',
            'youtube.com/c/',
            'youtube.com/@',
            'youtube.com/user/',
            'youtu.be/'
        ]
        
        if not any(pattern in url for pattern in youtube_patterns):
            raise ValidationError("올바른 YouTube URL을 입력해주세요.")
        
        # YouTubeExtractor로 채널 정보 추출 시도
        try:
            extractor = YouTubeExtractor()
            channel_info = extractor.get_channel_info(url)
            
            if not channel_info:
                raise ValidationError("채널 정보를 가져올 수 없습니다. URL을 다시 확인해주세요.")
            
            # 폼 인스턴스에 채널 정보 저장 (save 메서드에서 사용)
            self.channel_info = channel_info
            
            # 중복 채널 확인
            if Channel.objects.filter(channel_id=channel_info['channel_id']).exists():
                raise ValidationError("이미 등록된 채널입니다.")
            
            return url
            
        except Exception as e:
            logger.error(f"채널 정보 추출 실패: {url}, 에러: {e}")
            raise ValidationError("채널 정보를 가져오는 중 오류가 발생했습니다.")
    
    def save(self, commit=True):
        """채널 정보를 자동으로 설정하여 저장"""
        instance = super().save(commit=False)
        
        # clean_youtube_url에서 추출한 채널 정보 사용
        if hasattr(self, 'channel_info'):
            instance.channel_id = self.channel_info['channel_id']
            instance.name = self.channel_info['channel_name']
            instance.url = self.channel_info['channel_url']
        
        if commit:
            instance.save()
        
        return instance


class ChannelEditForm(forms.ModelForm):
    """채널 편집 폼"""
    
    class Meta:
        model = Channel
        fields = ['name', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'input input-bordered w-full'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'toggle toggle-primary'
            })
        }


class ChannelBulkActionForm(forms.Form):
    """채널 일괄 작업 폼"""
    
    ACTION_CHOICES = [
        ('activate', '활성화'),
        ('deactivate', '비활성화'),
        ('delete', '삭제'),
        ('check_now', '즉시 확인'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'select select-bordered'})
    )
    channel_ids = forms.CharField(
        widget=forms.HiddenInput()
    )
    
    def clean_channel_ids(self):
        """선택된 채널 ID들 검증"""
        ids_str = self.cleaned_data.get('channel_ids', '')
        if not ids_str:
            raise ValidationError("선택된 채널이 없습니다.")
        
        try:
            ids = [int(id_str.strip()) for id_str in ids_str.split(',') if id_str.strip()]
            if not ids:
                raise ValidationError("선택된 채널이 없습니다.")
            return ids
        except ValueError:
            raise ValidationError("잘못된 채널 ID입니다.")