"""
코어 앱 테스트
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock
from channels.models import Channel, LiveStream
from downloads.models import Download
from core.models import Settings, SystemLog
from core.utils import YouTubeLiveChecker, sanitize_filename, format_file_size
from core.services import ChannelManagementService

User = get_user_model()


class SettingsModelTest(TestCase):
    """Settings 모델 테스트"""
    
    def test_set_and_get_setting(self):
        """설정 저장 및 조회 테스트"""
        # 정수 설정
        Settings.set_setting('test_int', 42, 'integer', '테스트 정수')
        self.assertEqual(Settings.get_setting('test_int'), 42)
        
        # 문자열 설정
        Settings.set_setting('test_string', 'hello', 'string', '테스트 문자열')
        self.assertEqual(Settings.get_setting('test_string'), 'hello')
        
        # 불린 설정
        Settings.set_setting('test_bool', 'true', 'boolean', '테스트 불린')
        self.assertTrue(Settings.get_setting('test_bool'))
        
        # 기본값 테스트
        self.assertEqual(Settings.get_setting('nonexistent', 'default'), 'default')
    
    def test_typed_value_conversion(self):
        """타입별 값 변환 테스트"""
        setting = Settings.objects.create(
            key='test_int',
            value='123',
            value_type='integer'
        )
        self.assertEqual(setting.get_typed_value(), 123)
        self.assertIsInstance(setting.get_typed_value(), int)
        
        setting = Settings.objects.create(
            key='test_bool',
            value='false',
            value_type='boolean'
        )
        self.assertFalse(setting.get_typed_value())
        self.assertIsInstance(setting.get_typed_value(), bool)


class SystemLogTest(TestCase):
    """SystemLog 테스트"""
    
    def test_log_creation(self):
        """로그 생성 테스트"""
        log = SystemLog.log('INFO', 'test', '테스트 메시지', {'key': 'value'})
        
        self.assertEqual(log.level, 'INFO')
        self.assertEqual(log.category, 'test')
        self.assertEqual(log.message, '테스트 메시지')
        self.assertEqual(log.data, {'key': 'value'})


class UtilsTest(TestCase):
    """유틸리티 함수 테스트"""
    
    def test_sanitize_filename(self):
        """파일명 안전화 테스트"""
        self.assertEqual(sanitize_filename('test<>:"/\\|?*file'), 'test_________file')
        self.assertEqual(sanitize_filename('normal_file.txt'), 'normal_file.txt')
        
        # 길이 제한 테스트
        long_name = 'a' * 250
        sanitized = sanitize_filename(long_name)
        self.assertLessEqual(len(sanitized), 200)
    
    def test_format_file_size(self):
        """파일 크기 포맷팅 테스트"""
        self.assertEqual(format_file_size(0), '0B')
        self.assertEqual(format_file_size(1024), '1.0 KB')
        self.assertEqual(format_file_size(1024 * 1024), '1.0 MB')
        self.assertEqual(format_file_size(1024 * 1024 * 1024), '1.0 GB')


class YouTubeLiveCheckerTest(TestCase):
    """YouTube 라이브 체커 테스트"""
    
    def setUp(self):
        self.checker = YouTubeLiveChecker()
    
    def test_extract_channel_id_from_channel_url(self):
        """채널 URL에서 채널 ID 추출 테스트"""
        url = "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxx"
        channel_id = self.checker.extract_channel_id(url)
        self.assertEqual(channel_id, "UCxxxxxxxxxxxxxxxxxx")


class ChannelManagementServiceTest(TestCase):
    """채널 관리 서비스 테스트"""
    
    @patch.object(YouTubeLiveChecker, 'get_channel_info')
    def test_add_duplicate_channel(self, mock_get_channel_info):
        """중복 채널 추가 테스트"""
        # 기존 채널 생성
        existing_channel = Channel.objects.create(
            channel_id='UCxxxxxxxxxxxxxxxxxx',
            name='Existing Channel',
            url='https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxx'
        )
        
        mock_get_channel_info.return_value = {
            'channel_id': 'UCxxxxxxxxxxxxxxxxxx',
            'channel_name': 'Test Channel',
            'channel_url': 'https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxx'
        }
        
        service = ChannelManagementService()
        channel = service.add_channel('https://www.youtube.com/@testchannel')
        
        # 기존 채널이 반환되어야 함
        self.assertEqual(channel.id, existing_channel.id)


class ChannelModelTest(TestCase):
    """Channel 모델 테스트"""
    
    def test_create_channel(self):
        """채널 생성 테스트"""
        channel = Channel.objects.create(
            channel_id='UCxxxxxxxxxxxxxxxxxx',
            name='Test Channel',
            url='https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxx'
        )
        
        self.assertEqual(str(channel), 'Test Channel (UCxxxxxxxxxxxxxxxxxx)')
        self.assertTrue(channel.is_active)
        self.assertIsNone(channel.last_checked)
    
    def test_update_last_checked(self):
        """마지막 확인 시간 업데이트 테스트"""
        channel = Channel.objects.create(
            channel_id='UCxxxxxxxxxxxxxxxxxx',
            name='Test Channel',
            url='https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxx'
        )
        
        self.assertIsNone(channel.last_checked)
        channel.update_last_checked()
        
        channel.refresh_from_db()
        self.assertIsNotNone(channel.last_checked)


class LiveStreamModelTest(TestCase):
    """LiveStream 모델 테스트"""
    
    def setUp(self):
        self.channel = Channel.objects.create(
            channel_id='UCxxxxxxxxxxxxxxxxxx',
            name='Test Channel',
            url='https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxx'
        )
    
    def test_create_live_stream(self):
        """라이브 스트림 생성 테스트"""
        stream = LiveStream.objects.create(
            channel=self.channel,
            video_id='test_video_id',
            title='Test Live Stream',
            url='https://www.youtube.com/watch?v=test_video_id'
        )
        
        self.assertEqual(stream.status, 'live')
        self.assertFalse(stream.notification_sent)
        self.assertIsNone(stream.ended_at)
    
    def test_mark_as_ended(self):
        """라이브 종료 처리 테스트"""
        stream = LiveStream.objects.create(
            channel=self.channel,
            video_id='test_video_id',
            title='Test Live Stream',
            url='https://www.youtube.com/watch?v=test_video_id'
        )
        
        stream.mark_as_ended()
        
        self.assertEqual(stream.status, 'ended')
        self.assertIsNotNone(stream.ended_at)


class DownloadModelTest(TestCase):
    """Download 모델 테스트"""
    
    def setUp(self):
        self.channel = Channel.objects.create(
            channel_id='UCxxxxxxxxxxxxxxxxxx',
            name='Test Channel',
            url='https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxx'
        )
        
        self.live_stream = LiveStream.objects.create(
            channel=self.channel,
            video_id='test_video_id',
            title='Test Live Stream',
            url='https://www.youtube.com/watch?v=test_video_id'
        )
    
    def test_create_download(self):
        """다운로드 생성 테스트"""
        download = Download.objects.create(
            live_stream=self.live_stream,
            quality='low'
        )
        
        self.assertEqual(download.status, 'pending')
        self.assertIsNotNone(download.delete_after)
    
    def test_download_status_methods(self):
        """다운로드 상태 변경 메서드 테스트"""
        download = Download.objects.create(
            live_stream=self.live_stream,
            quality='high'
        )
        
        # 다운로드 시작
        download.mark_as_downloading()
        self.assertEqual(download.status, 'downloading')
        self.assertIsNotNone(download.download_started_at)
        
        # 다운로드 완료
        download.mark_as_completed('/path/to/file.mp4', 1024000)
        self.assertEqual(download.status, 'completed')
        self.assertEqual(download.file_path, '/path/to/file.mp4')
        self.assertEqual(download.file_size, 1024000)
        self.assertIsNotNone(download.download_completed_at)
        
        # 다운로드 실패 (새 인스턴스로 테스트)
        failed_download = Download.objects.create(
            live_stream=self.live_stream,
            quality='low'
        )
        
        failed_download.mark_as_failed('Test error message')
        self.assertEqual(failed_download.status, 'failed')
        self.assertEqual(failed_download.error_message, 'Test error message')
