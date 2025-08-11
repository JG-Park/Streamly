"""
API 뷰들
"""

import os
from datetime import datetime, timedelta
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import status, viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from channels.models import Channel, LiveStream
from core.models import Settings, SystemLog

# downloads.models는 나중에 임포트 (순환 임포트 방지)
try:
    from downloads.models import Download
except ImportError:
    # 마이그레이션 중일 때는 임포트 실패 허용
    Download = None
from core.services import ChannelManagementService
from core.telegram_service import TelegramService
from core.utils import format_file_size
import logging
import re

logger = logging.getLogger('streamly')
from .serializers import (
    ChannelSerializer, ChannelCreateSerializer, LiveStreamSerializer,
    DownloadSerializer, SettingsSerializer, SystemLogSerializer,
    DashboardStatsSerializer, TelegramTestSerializer
)


class ChannelViewSet(viewsets.ModelViewSet):
    """채널 API ViewSet"""
    queryset = Channel.objects.all().order_by('-is_active', 'name')
    serializer_class = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return ChannelCreateSerializer
        return ChannelSerializer
    
    def create(self, request):
        """새 채널 추가 (비동기 처리)"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        channel_url = serializer.validated_data['url']
        
        # Celery 태스크로 비동기 처리
        from core.tasks import add_channel_async
        result = add_channel_async.delay(channel_url)
        
        # 채널 미리보기 정보로 임시 응답
        from core.utils import YouTubeLiveChecker
        checker = YouTubeLiveChecker()
        preview_info = checker.get_channel_info(channel_url)
        
        if preview_info:
            # 임시 채널 객체 생성 (비동기 작업이 완료되면 업데이트됨)
            from channels.models import Channel
            channel, created = Channel.objects.get_or_create(
                channel_id=preview_info['channel_id'],
                defaults={
                    'name': preview_info['channel_name'],
                    'url': preview_info['channel_url'],
                    'is_active': True,
                    'check_interval_minutes': 1,
                }
            )
            
            if not created:
                return Response(
                    {'error': '이미 등록된 채널입니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            response_serializer = ChannelSerializer(channel)
            return Response({
                **response_serializer.data,
                'task_id': str(result.id),
                'message': '채널을 추가하고 있습니다. 잠시 후 화면이 새로고침됩니다.'
            }, status=status.HTTP_201_CREATED)
        else:
            return Response(
                {'error': '채널 정보를 가져올 수 없습니다. URL을 확인해주세요.'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def toggle(self, request, pk=None):
        """채널 활성/비활성 토글"""
        channel = self.get_object()
        channel.is_active = not channel.is_active
        channel.save(update_fields=['is_active'])
        
        SystemLog.log(
            'INFO', 'system', 
            f"채널 {channel.name} {'활성화' if channel.is_active else '비활성화'}",
            {'channel_id': channel.channel_id}
        )
        
        return Response({
            'success': True,
            'message': f"채널이 {'활성화' if channel.is_active else '비활성화'}되었습니다.",
            'is_active': channel.is_active
        })
    
    @action(detail=True, methods=['get'])
    def live_streams(self, request, pk=None):
        """채널의 라이브 스트림 목록"""
        channel = self.get_object()
        live_streams = channel.live_streams.all()
        
        page = self.paginate_queryset(live_streams)
        if page is not None:
            serializer = LiveStreamSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = LiveStreamSerializer(live_streams, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def check_now(self, request, pk=None):
        """채널 즉시 체크"""
        channel = self.get_object()
        
        # Celery 태스크로 즉시 체크 실행
        from core.tasks import check_channel_live_streams
        result = check_channel_live_streams.delay(channel.id)
        
        SystemLog.log(
            'INFO', 'system',
            f"채널 {channel.name} 즉시 체크 시작",
            {'channel_id': channel.channel_id, 'task_id': str(result.id)}
        )
        
        return Response({
            'message': f'{channel.name} 채널 체크를 시작했습니다.',
            'task_id': str(result.id),
            'channel': ChannelSerializer(channel).data
        })
    
    @action(detail=True, methods=['post'])
    def update_check_interval(self, request, pk=None):
        """채널 체크 주기 업데이트"""
        channel = self.get_object()
        interval_minutes = request.data.get('check_interval_minutes')
        
        if not interval_minutes:
            return Response(
                {'error': 'check_interval_minutes가 필요합니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            interval_minutes = int(interval_minutes)
            if interval_minutes < 1 or interval_minutes > 60:
                raise ValueError("체크 주기는 1-60분 사이여야 합니다.")
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 채널 체크 주기 업데이트
        channel.check_interval_minutes = interval_minutes
        channel.save(update_fields=['check_interval_minutes'])
        
        SystemLog.log(
            'INFO', 'system',
            f"채널 {channel.name} 체크 주기 변경: {interval_minutes}분",
            {'channel_id': channel.channel_id}
        )
        
        return Response({
            'success': True,
            'message': f'체크 주기가 {interval_minutes}분으로 변경되었습니다.',
            'channel': ChannelSerializer(channel).data
        })


class LiveStreamViewSet(viewsets.ReadOnlyModelViewSet):
    """라이브 스트림 API ViewSet"""
    queryset = LiveStream.objects.select_related('channel').all()
    serializer_class = LiveStreamSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ['-started_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # 필터링
        status_filter = self.request.query_params.get('status')
        channel_id = self.request.query_params.get('channel')
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if channel_id:
            queryset = queryset.filter(channel_id=channel_id)
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def downloads(self, request, pk=None):
        """라이브 스트림의 다운로드 목록"""
        live_stream = self.get_object()
        downloads = live_stream.downloads.all()
        
        serializer = DownloadSerializer(downloads, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def force_status_change(self, request, pk=None):
        """라이브 스트림 상태 강제 변경"""
        live_stream = self.get_object()
        new_status = request.data.get('status')
        
        # 허용된 상태 목록
        allowed_statuses = ['live', 'ended', 'completed', 'downloading', 'failed']
        
        if not new_status or new_status not in allowed_statuses:
            return Response(
                {'error': f'유효하지 않은 상태입니다. 허용된 상태: {", ".join(allowed_statuses)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        old_status = live_stream.status
        live_stream.status = new_status
        live_stream.save(update_fields=['status'])
        
        SystemLog.log('INFO', 'stream_status', 
                     f"스트림 상태 강제 변경: {live_stream.title}",
                     {
                         'stream_id': live_stream.id,
                         'old_status': old_status,
                         'new_status': new_status,
                         'channel_name': live_stream.channel.name
                     })
        
        return Response({
            'message': f'스트림 상태가 "{old_status}"에서 "{new_status}"로 변경되었습니다.',
            'old_status': old_status,
            'new_status': new_status
        })
    
    @action(detail=True, methods=['post'])
    def create_download_tasks(self, request, pk=None):
        """라이브 스트림의 다운로드 작업 생성"""
        live_stream = self.get_object()
        
        if live_stream.status not in ['ended', 'completed']:
            return Response(
                {'error': '종료된 라이브 스트림만 다운로드할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 다운로드 작업 생성
        from core.services import StreamEndHandler
        handler = StreamEndHandler()
        created_count = handler.create_download_tasks(live_stream)
        
        if created_count > 0:
            live_stream.status = 'downloading'
            live_stream.save(update_fields=['status'])
            
            # Download 모델이 사용 가능한 경우에만 다운로드 시작
            if Download is not None:
                # 저화질 다운로드부터 시작
                low_download = Download.objects.filter(
                    live_stream=live_stream, 
                    quality='worst',  # 'low' -> 'worst'로 수정
                    status='pending'
                ).first()
            else:
                low_download = None
            
            if low_download:
                from core.tasks import download_video
                download_video.delay(low_download.id)
            
            SystemLog.log('INFO', 'download', 
                         f"다운로드 작업 생성: {live_stream.title}",
                         {'stream_id': live_stream.id, 'created_count': created_count})
        
        return Response({
            'message': f'{created_count}개의 다운로드 작업이 생성되었습니다.',
            'created_count': created_count
        })
    
    @action(detail=True, methods=['post']) 
    def reset_download_status(self, request, pk=None):
        """라이브 스트림의 다운로드 상태 초기화"""
        live_stream = self.get_object()
        
        # 모든 다운로드 상태 초기화
        failed_downloads = live_stream.downloads.filter(status__in=['downloading', 'failed'])
        reset_count = failed_downloads.count()
        
        failed_downloads.update(status='pending', error_message=None)
        
        # 스트림 상태도 초기화
        if live_stream.status == 'downloading':
            live_stream.status = 'ended'
            live_stream.save(update_fields=['status'])
        
        SystemLog.log('INFO', 'download', 
                     f"다운로드 상태 초기화: {live_stream.title}",
                     {'stream_id': live_stream.id, 'reset_count': reset_count})
        
        return Response({
            'message': f'{reset_count}개의 다운로드 상태가 초기화되었습니다.',
            'reset_count': reset_count
        })


class DownloadViewSet(viewsets.ReadOnlyModelViewSet):
    """다운로드 API ViewSet"""
    serializer_class = DownloadSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ['-created_at']
    
    @property
    def queryset(self):
        """Download 모델 동적 임포트"""
        from downloads.models import Download
        return Download.objects.select_related('live_stream__channel').all()
    
    @action(detail=False, methods=['get'])
    def pending(self, request):
        """대기 중인 다운로드 목록"""
        pending_downloads = self.get_queryset().filter(status='pending')
        serializer = self.get_serializer(pending_downloads, many=True)
        return Response({
            'count': pending_downloads.count(),
            'results': serializer.data
        })
    
    def get_queryset(self):
        from downloads.models import Download
        queryset = Download.objects.select_related('live_stream__channel').all()
        
        # 필터링
        status_filter = self.request.query_params.get('status')
        quality_filter = self.request.query_params.get('quality')
        channel_id = self.request.query_params.get('channel')
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if quality_filter:
            queryset = queryset.filter(quality=quality_filter)
        
        if channel_id:
            queryset = queryset.filter(live_stream__channel_id=channel_id)
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def retry_download(self, request, pk=None):
        """다운로드 재시도"""
        download = self.get_object()
        
        if download.status != 'failed':
            return Response(
                {'error': '실패한 다운로드만 재시도할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 다운로드 상태 초기화
        download.status = 'pending'
        download.error_message = None
        download.save(update_fields=['status', 'error_message'])
        
        # 다운로드 태스크 재시작
        from core.tasks import download_video
        download_video.delay(download.id)
        
        serializer = self.get_serializer(download)
        return Response(serializer.data)
    
    @action(detail=True, methods=['delete'])
    def delete_file(self, request, pk=None):
        """다운로드 파일 삭제"""
        download = self.get_object()
        
        if download.status != 'completed':
            return Response(
                {'error': '완료된 다운로드만 삭제할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        success = download.delete_file()
        
        if success:
            download.delete()  # DB 레코드도 삭제
            SystemLog.log('INFO', 'download', 
                         f"다운로드 파일 삭제: {download.live_stream.title}",
                         {'download_id': download.id})
            return Response({'message': '파일이 삭제되었습니다.'})
        else:
            return Response(
                {'error': '파일 삭제에 실패했습니다.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def start_download(self, request, pk=None):
        """다운로드 시작 (수동 요청)"""
        download = self.get_object()
        
        if download.status != 'pending':
            return Response(
                {'error': '대기 중인 다운로드만 시작할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 다운로드 태스크 시작
        from core.tasks import download_video
        task_result = download_video.delay(download.id)
        
        SystemLog.log('INFO', 'download', 
                     f"수동 다운로드 시작: {download.live_stream.title}",
                     {'download_id': download.id, 'task_id': str(task_result.id)})
        
        return Response({
            'message': '다운로드를 시작했습니다.',
            'task_id': str(task_result.id)
        })
    
    @action(detail=True, methods=['post'])
    def force_download(self, request, pk=None):
        """강제 다운로드 시작 (상태 무시)"""
        download = self.get_object()
        
        if download.status == 'completed':
            return Response(
                {'error': '이미 완료된 다운로드입니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 강제 다운로드 태스크 시작
        from core.tasks import force_start_download
        task_result = force_start_download.delay(download.id)
        
        SystemLog.log('INFO', 'download', 
                     f"강제 다운로드 시작: {download.live_stream.title}",
                     {'download_id': download.id, 'task_id': str(task_result.id)})
        
        return Response({
            'message': '강제로 다운로드를 시작했습니다.',
            'task_id': str(task_result.id)
        })
    
    @action(detail=True, methods=['post'])
    def cancel_download(self, request, pk=None):
        """다운로드 중지"""
        download = self.get_object()
        
        if download.status not in ['pending', 'downloading']:
            return Response(
                {'error': '진행 중인 다운로드만 중지할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 다운로드 상태를 실패로 변경
        download.mark_as_failed('사용자에 의해 취소됨')
        
        # Celery 태스크 취소 시도 (현재 작업 중인 경우)
        try:
            from celery import current_app
            # 진행 중인 태스크들 확인 후 취소
            inspect = current_app.control.inspect()
            active_tasks = inspect.active()
            
            if active_tasks:
                for worker, tasks in active_tasks.items():
                    for task in tasks:
                        if (task.get('name') == 'core.tasks.download_video' and 
                            task.get('args') and str(download.id) in str(task['args'])):
                            current_app.control.revoke(task['id'], terminate=True)
                            logger.info(f"Celery 태스크 취소: {task['id']}")
        except Exception as e:
            logger.error(f"다운로드 태스크 취소 실패: {e}")
        
        SystemLog.log('INFO', 'download', 
                     f"다운로드 취소: {download.live_stream.title}",
                     {'download_id': download.id})
        
        return Response({'message': '다운로드가 취소되었습니다.'})
    
    @action(detail=True, methods=['post'])
    def reset_status(self, request, pk=None):
        """다운로드 상태 초기화"""
        download = self.get_object()
        
        if download.status == 'completed':
            return Response(
                {'error': '완료된 다운로드는 초기화할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        old_status = download.status
        download.status = 'pending'
        download.error_message = None
        download.started_at = None
        download.save(update_fields=['status', 'error_message', 'started_at'])
        
        SystemLog.log('INFO', 'download', 
                     f"다운로드 상태 초기화: {download.live_stream.title}",
                     {'download_id': download.id, 'old_status': old_status})
        
        return Response({
            'message': f'다운로드 상태가 "{old_status}"에서 "pending"으로 초기화되었습니다.',
            'old_status': old_status,
            'new_status': 'pending'
        })
    
    @action(detail=True, methods=['get'])
    def download_file(self, request, pk=None):
        """로컬 파일 다운로드"""
        download = self.get_object()
        
        if download.status != 'completed' or not download.file_path:
            return Response(
                {'error': '완료된 다운로드 파일만 다운로드할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not download.file_exists:
            return Response(
                {'error': '파일이 존재하지 않습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            from django.http import FileResponse
            import mimetypes
            
            # 파일 타입 감지
            content_type, _ = mimetypes.guess_type(download.file_path)
            if not content_type:
                content_type = 'application/octet-stream'
            
            # 파일명 생성 (안전한 파일명)
            filename = f"{download.live_stream.channel.name}_{download.live_stream.title}_{download.get_quality_display()}.{download.file_path.split('.')[-1]}"
            safe_filename = ''.join(c for c in filename if c.isalnum() or c in '._-')
            
            response = FileResponse(
                open(download.file_path, 'rb'),
                content_type=content_type,
                as_attachment=True,
                filename=safe_filename
            )
            
            SystemLog.log('INFO', 'download', 
                         f"파일 다운로드: {download.live_stream.title}",
                         {'download_id': download.id, 'filename': safe_filename})
            
            return response
            
        except Exception as e:
            return Response(
                {'error': f'파일 다운로드 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'], url_path='file')
    def file(self, request, pk=None):
        """파일 스트리밍/다운로드 (브라우저 재생용)"""
        download = self.get_object()
        
        if download.status != 'completed' or not download.file_path:
            return Response(
                {'error': '완료된 다운로드 파일만 재생할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not download.file_exists:
            return Response(
                {'error': '파일이 존재하지 않습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            from django.http import FileResponse, HttpResponse
            import mimetypes
            import os
            
            # 파일 타입 감지
            content_type, _ = mimetypes.guess_type(download.file_path)
            if not content_type:
                content_type = 'video/mp4' if download.file_path.endswith('.mp4') else 'application/octet-stream'
            
            # 파일 크기
            file_size = os.path.getsize(download.file_path)
            
            # Range 헤더 처리 (비디오 스트리밍을 위해)
            range_header = request.META.get('HTTP_RANGE', None)
            if range_header:
                # Range 요청 처리
                try:
                    byte_start = 0
                    byte_end = file_size - 1
                    
                    if range_header:
                        match = re.search(r'bytes=(\d+)-(\d*)', range_header)
                        if match:
                            byte_start = int(match.group(1))
                            if match.group(2):
                                byte_end = int(match.group(2))
                    
                    # 부분 콘텐츠 응답
                    length = byte_end - byte_start + 1
                    response = HttpResponse(status=206)  # Partial Content
                    response['Content-Type'] = content_type
                    response['Content-Length'] = str(length)
                    response['Content-Range'] = f'bytes {byte_start}-{byte_end}/{file_size}'
                    response['Accept-Ranges'] = 'bytes'
                    
                    # 파일 읽기
                    with open(download.file_path, 'rb') as f:
                        f.seek(byte_start)
                        response.content = f.read(length)
                    
                    return response
                    
                except Exception as e:
                    logger.error(f"Range 요청 처리 실패: {e}")
            
            # 일반 요청 (전체 파일)
            response = FileResponse(
                open(download.file_path, 'rb'),
                content_type=content_type,
                as_attachment=False  # 브라우저에서 직접 재생
            )
            
            # 파일명 설정
            filename = os.path.basename(download.file_path)
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            response['Accept-Ranges'] = 'bytes'
            response['Content-Length'] = str(file_size)
            
            return response
            
        except Exception as e:
            logger.error(f"파일 스트리밍 실패: {e}")
            return Response(
                {'error': f'파일 스트리밍 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SettingsViewSet(viewsets.ModelViewSet):
    """설정 API ViewSet"""
    queryset = Settings.objects.all().order_by('key')
    serializer_class = SettingsSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'key'
    
    @action(detail=False, methods=['get', 'post'])
    def retention_days(self, request):
        """보관 기간 설정"""
        if request.method == 'GET':
            retention_days = Settings.get_setting('retention_days', 14)
            return Response({'retention_days': retention_days})
        
        elif request.method == 'POST':
            days = request.data.get('retention_days')
            if not isinstance(days, int) or days < 1:
                return Response(
                    {'error': '보관 기간은 1일 이상이어야 합니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            Settings.set_setting('retention_days', days, 'integer', '파일 보관 기간(일)')
            return Response({'retention_days': days})
    
    @action(detail=False, methods=['get', 'post'])
    def telegram_config(self, request):
        """텔레그램 설정"""
        if request.method == 'GET':
            bot_token = Settings.get_setting('telegram_bot_token', '')
            chat_id = Settings.get_setting('telegram_chat_id', '')
            
            # 보안을 위해 토큰은 마스킹
            masked_token = ''
            if bot_token:
                masked_token = bot_token[:10] + '*' * (len(bot_token) - 20) + bot_token[-10:] if len(bot_token) > 20 else '*' * len(bot_token)
            
            return Response({
                'bot_token': masked_token,
                'chat_id': chat_id
            })
        
        elif request.method == 'POST':
            bot_token = request.data.get('bot_token', '').strip()
            chat_id = request.data.get('chat_id', '').strip()
            notify_live_start = request.data.get('notify_live_start', True)
            notify_download_complete = request.data.get('notify_download_complete', True)
            notify_errors = request.data.get('notify_errors', True)
            
            if bot_token and not bot_token.startswith('*'):  # 마스킹된 토큰이 아닌 경우만
                Settings.set_setting('telegram_bot_token', bot_token, 'string', '텔레그램 봇 토큰')
            if chat_id:
                Settings.set_setting('telegram_chat_id', chat_id, 'string', '텔레그램 채팅 ID')
            
            # 알림 설정 저장
            Settings.set_setting('notify_live_start', notify_live_start, 'boolean', '라이브 시작 알림')
            Settings.set_setting('notify_download_complete', notify_download_complete, 'boolean', '다운로드 완료 알림')
            Settings.set_setting('notify_errors', notify_errors, 'boolean', '오류 알림')
            
            return Response({'message': '텔레그램 설정이 저장되었습니다.'})
    
    @action(detail=False, methods=['post'])
    def general(self, request):
        """일반 설정 저장"""
        retention_days = request.data.get('retention_days')
        check_interval = request.data.get('check_interval')
        default_quality = request.data.get('default_quality')
        
        if retention_days:
            Settings.set_setting('retention_days', int(retention_days), 'integer', '다운로드 보관 기간(일)')
        
        if check_interval:
            Settings.set_setting('check_interval_minutes', int(check_interval), 'integer', '기본 체크 주기(분)')
        
        if default_quality:
            Settings.set_setting('default_quality', default_quality, 'string', '기본 다운로드 품질')
        
        return Response({'message': '일반 설정이 저장되었습니다.'})
    
    @action(detail=False, methods=['post'])
    def update_ytdlp(self, request):
        """yt-dlp 업데이트"""
        try:
            import subprocess
            result = subprocess.run(['pip', 'install', '--upgrade', 'yt-dlp'], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0:
                SystemLog.log('INFO', 'system', 'yt-dlp 업데이트 완료')
                return Response({'message': 'yt-dlp가 업데이트되었습니다.'})
            else:
                raise Exception(result.stderr)
        except Exception as e:
            logger.error(f"yt-dlp 업데이트 실패: {e}")
            return Response(
                {'error': f'업데이트 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def cleanup_files(self, request):
        """오래된 파일 정리"""
        try:
            from core.tasks import cleanup_old_downloads
            result = cleanup_old_downloads.delay()
            task_result = result.get(timeout=300)  # 5분 대기
            
            SystemLog.log('INFO', 'system', 
                         f'파일 정리 완료: {task_result["deleted_files"]}개 삭제')
            
            return Response({
                'message': f'{task_result["deleted_files"]}개의 파일이 삭제되었습니다.',
                'deleted_count': task_result["deleted_files"]
            })
        except Exception as e:
            logger.error(f"파일 정리 실패: {e}")
            return Response(
                {'error': f'파일 정리 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def clear_downloads(self, request):
        """모든 다운로드 삭제"""
        try:
            # 모든 다운로드 파일 삭제
            downloads = Download.objects.all()
            deleted_files = 0
            deleted_records = downloads.count()
            
            for download in downloads:
                if download.delete_file():
                    deleted_files += 1
            
            # DB 레코드 삭제
            downloads.delete()
            
            # 스트림 상태도 초기화
            LiveStream.objects.filter(status='downloading').update(status='ended')
            
            SystemLog.log('INFO', 'system', 
                         f'모든 다운로드 삭제: 파일 {deleted_files}개, 레코드 {deleted_records}개')
            
            return Response({
                'message': f'{deleted_files}개의 파일과 {deleted_records}개의 레코드가 삭제되었습니다.',
                'deleted_files': deleted_files,
                'deleted_records': deleted_records
            })
        except Exception as e:
            logger.error(f"다운로드 삭제 실패: {e}")
            return Response(
                {'error': f'다운로드 삭제 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def clear_logs(self, request):
        """로그 삭제"""
        try:
            deleted_count = SystemLog.objects.all().delete()[0]
            
            SystemLog.log('INFO', 'system', f'로그 삭제 완료: {deleted_count}개')
            
            return Response({
                'message': f'{deleted_count}개의 로그가 삭제되었습니다.',
                'deleted_count': deleted_count
            })
        except Exception as e:
            logger.error(f"로그 삭제 실패: {e}")
            return Response(
                {'error': f'로그 삭제 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def fix_download_status(self, request):
        """다운로드 상태 불일치 수정"""
        try:
            from django.core.management import call_command
            from io import StringIO
            
            # 명령어 출력 캡처
            out = StringIO()
            call_command('fix_download_status', 
                        '--fix-stuck-downloads', 
                        '--fix-stuck-streams', 
                        stdout=out)
            output = out.getvalue()
            
            SystemLog.log('INFO', 'system', '다운로드 상태 수정 실행')
            
            return Response({
                'message': '다운로드 상태 수정이 완료되었습니다.',
                'output': output
            })
        except Exception as e:
            logger.error(f"다운로드 상태 수정 실패: {e}")
            return Response(
                {'error': f'상태 수정 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def process_pending_downloads(self, request):
        """대기 중 다운로드 즉시 처리"""
        try:
            from core.tasks import process_pending_downloads
            
            # 비동기 태스크 실행
            result = process_pending_downloads.delay()
            task_result = result.get(timeout=60)  # 1분 대기
            
            SystemLog.log('INFO', 'system', 
                         f"대기 중 다운로드 처리: {task_result['processed_count']}개 시작")
            
            return Response({
                'message': f"{task_result['processed_count']}개의 대기 중 다운로드를 시작했습니다.",
                'processed_count': task_result['processed_count'],
                'started_downloads': task_result['started_downloads']
            })
        except Exception as e:
            logger.error(f"대기 중 다운로드 처리 실패: {e}")
            return Response(
                {'error': f'대기 중 다운로드 처리 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SystemLogViewSet(viewsets.ReadOnlyModelViewSet):
    """시스템 로그 API ViewSet"""
    queryset = SystemLog.objects.all()
    serializer_class = SystemLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ['-created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # 필터링
        level_filter = self.request.query_params.get('level')
        category_filter = self.request.query_params.get('category')
        
        if level_filter:
            queryset = queryset.filter(level=level_filter)
        
        if category_filter:
            queryset = queryset.filter(category=category_filter)
        
        return queryset


class DashboardAPIView(APIView):
    """대시보드 통계 API"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """대시보드 통계 데이터"""
        # 기본 통계
        total_channels = Channel.objects.count()
        active_channels = Channel.objects.filter(is_active=True).count()
        total_live_streams = LiveStream.objects.count()
        current_live_count = LiveStream.objects.filter(status='live').count()
        
        # 다운로드 통계
        download_stats = Download.objects.aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
            pending=Count('id', filter=Q(status='pending')),
            failed=Count('id', filter=Q(status='failed')),
            total_size=Sum('file_size', filter=Q(status='completed'))
        )
        
        # 스토리지 사용량
        total_storage_bytes = download_stats['total_size'] or 0
        total_storage_used = format_file_size(total_storage_bytes)
        
        # 최근 활동
        recent_activities = []
        
        # 최근 라이브 스트림
        recent_streams = LiveStream.objects.select_related('channel').order_by('-started_at')[:5]
        for stream in recent_streams:
            recent_activities.append({
                'type': 'live_stream',
                'message': f"{stream.channel.name}에서 라이브 시작: {stream.title}",
                'timestamp': stream.started_at,
                'status': stream.status
            })
        
        # 최근 다운로드
        recent_downloads = Download.objects.select_related('live_stream__channel').order_by('-created_at')[:5]
        for download in recent_downloads:
            recent_activities.append({
                'type': 'download',
                'message': f"다운로드 {download.get_status_display()}: {download.live_stream.title}",
                'timestamp': download.created_at,
                'status': download.status
            })
        
        # 시간순 정렬
        recent_activities.sort(key=lambda x: x['timestamp'], reverse=True)
        recent_activities = recent_activities[:10]
        
        data = {
            'total_channels': total_channels,
            'active_channels': active_channels,
            'total_live_streams': total_live_streams,
            'current_live_count': current_live_count,
            'total_downloads': download_stats['total'],
            'completed_downloads': download_stats['completed'],
            'pending_downloads': download_stats['pending'],
            'failed_downloads': download_stats['failed'],
            'total_storage_used': total_storage_used,
            'recent_activities': recent_activities
        }
        
        serializer = DashboardStatsSerializer(data)
        return Response(serializer.data)


class TelegramTestAPIView(APIView):
    """텔레그램 테스트 API"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """텔레그램 메시지 테스트 전송"""
        serializer = TelegramTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        telegram = TelegramService()
        message = serializer.validated_data['message']
        
        success = telegram.send_message(message)
        
        if success:
            return Response({'message': '테스트 메시지가 전송되었습니다.'})
        else:
            return Response(
                {'error': '메시지 전송에 실패했습니다. 텔레그램 설정을 확인해주세요.'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def get(self, request):
        """텔레그램 연결 테스트"""
        telegram = TelegramService()
        result = telegram.test_connection()
        
        if result['success']:
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)


class ChannelPreviewView(APIView):
    """채널 미리보기 API"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """YouTube URL로 채널 정보 미리보기"""
        url = request.data.get('url', '').strip()
        
        if not url:
            return Response(
                {'error': 'URL이 필요합니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from core.utils import YouTubeLiveChecker
            checker = YouTubeLiveChecker()
            channel_info = checker.get_channel_info(url)
            
            if not channel_info:
                return Response(
                    {'error': '채널 정보를 가져올 수 없습니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 중복 확인
            is_duplicate = Channel.objects.filter(
                channel_id=channel_info['channel_id']
            ).exists()
            
            return Response({
                'success': True,
                'channel': {
                    'name': channel_info['channel_name'],
                    'channel_id': channel_info['channel_id'],
                    'url': channel_info['channel_url'],
                    'is_duplicate': is_duplicate
                }
            })
            
        except Exception as e:
            return Response(
                {'error': f'채널 정보 조회 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DashboardStatsView(APIView):
    """대시보드 통계 API"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """대시보드 통계 조회"""
        stats = {
            'total_channels': Channel.objects.count(),
            'active_channels': Channel.objects.filter(is_active=True).count(),
            'total_streams': LiveStream.objects.count(),
            'live_streams': LiveStream.objects.filter(status='live').count(),
            'total_downloads': Download.objects.count(),
            'completed_downloads': Download.objects.filter(status='completed').count(),
            'pending_downloads': Download.objects.filter(status='pending').count(),
            'failed_downloads': Download.objects.filter(status='failed').count(),
        }
        
        # 저장 공간 사용량
        total_size = Download.objects.filter(status='completed').aggregate(
            total=Sum('file_size')
        )['total'] or 0
        stats['total_storage_used'] = format_file_size(total_size)
        
        return Response(stats)


class SystemManagementView(APIView):
    """시스템 관리 API"""
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['post'])
    def fix_download_status(self, request):
        """다운로드 상태 불일치 수정"""
        try:
            from django.core.management import call_command
            from io import StringIO
            
            # 명령어 출력 캡처
            out = StringIO()
            call_command('fix_download_status', '--fix-stuck-downloads', '--fix-stuck-streams', stdout=out)
            output = out.getvalue()
            
            SystemLog.log('INFO', 'system', '다운로드 상태 수정 실행')
            
            return Response({
                'message': '다운로드 상태 수정이 완료되었습니다.',
                'output': output
            })
            
        except Exception as e:
            logger.error(f"다운로드 상태 수정 실패: {e}")
            return Response(
                {'error': f'상태 수정 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """시스템 관리 작업 실행"""
        action = request.data.get('action')
        
        if action == 'fix_download_status':
            return self.fix_download_status(request)
        
        return Response(
            {'error': '지원되지 않는 작업입니다.'},
            status=status.HTTP_400_BAD_REQUEST
        )
