"""
Streamly 핵심 서비스 로직
"""

import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from typing import List, Optional, Dict, Any

from channels.models import Channel, LiveStream
from downloads.models import Download
from core.models import SystemLog
from core.utils import YouTubeLiveChecker
from core.duplicate_detection import duplicate_detection_service
from core.youtube_monitor import efficient_monitor, hybrid_service

logger = logging.getLogger('streamly')


class ChannelMonitorService:
    """채널 모니터링 서비스"""
    
    def __init__(self):
        self.youtube_checker = YouTubeLiveChecker()
        # API 할당량 초과 시 자동으로 efficient_monitor 사용
        from core.api_backup_service import api_backup_service
        self.api_backup_service = api_backup_service
        self.use_efficient_monitor = False  # 기본값
    
    def check_all_active_channels(self) -> Dict[str, Any]:
        """모든 활성 채널의 라이브 스트림 확인"""
        results = {
            'checked_channels': 0,
            'new_streams': 0,
            'ended_streams': 0,
            'errors': 0,
            'channel_results': []
        }
        
        active_channels = Channel.objects.filter(is_active=True)
        
        for channel in active_channels:
            try:
                channel_result = self.check_channel_streams(channel)
                results['channel_results'].append(channel_result)
                results['checked_channels'] += 1
                results['new_streams'] += len(channel_result.get('new_streams', []))
                results['ended_streams'] += len(channel_result.get('ended_streams', []))
                
            except Exception as e:
                logger.error(f"채널 {channel.name} 확인 중 오류: {e}")
                results['errors'] += 1
                SystemLog.log('ERROR', 'channel_check', 
                            f"채널 {channel.name} 확인 실패", 
                            {'channel_id': channel.channel_id, 'error': str(e)})
        
        # 전체 결과 로그
        SystemLog.log('INFO', 'channel_check', 
                     f"채널 확인 완료: {results['checked_channels']}개, "
                     f"신규 스트림: {results['new_streams']}개, "
                     f"종료 스트림: {results['ended_streams']}개")
        
        return results
    
    def check_channel_streams(self, channel: Channel) -> Dict[str, Any]:
        """개별 채널의 라이브 스트림 확인"""
        result = {
            'channel': {
                'id': channel.id,
                'name': channel.name,
                'channel_id': channel.channel_id,
                'url': channel.url
            },
            'new_streams': [],
            'ended_streams': [],
            'error': None
        }
        
        try:
            # 채널 마지막 확인 시간 업데이트
            channel.update_last_checked()
            
            # 현재 라이브 스트림 확인 (yt-dlp 우선 사용)
            # yt-dlp를 기본으로 사용 (더 안정적이고 API 할당량 문제 없음)
            logger.info(f"채널 확인 중: {channel.name} ({channel.channel_id})")
            
            # YouTubeLiveChecker가 이미 yt-dlp 우선으로 설정됨
            live_streams = self.youtube_checker.check_live_streams(channel.channel_id)
                
            current_live_ids = {stream['video_id'] for stream in live_streams}
            
            # 새로운 라이브 스트림 처리
            existing_live_ids = set(
                LiveStream.objects.filter(
                    channel=channel,
                    status__in=['live', 'downloading']
                ).values_list('video_id', flat=True)
            )
            
            # 새로 시작된 라이브 스트림
            new_live_ids = current_live_ids - existing_live_ids
            for stream_info in live_streams:
                if stream_info['video_id'] in new_live_ids:
                    live_stream = self.create_live_stream(channel, stream_info)
                    if live_stream:
                        result['new_streams'].append(live_stream)
            
            # 종료된 라이브 스트림 확인
            # DB에서 live 상태인 모든 스트림 가져오기
            db_live_streams = LiveStream.objects.filter(
                channel=channel,
                status='live'
            )
            db_live_ids = set(db_live_streams.values_list('video_id', flat=True))
            
            # 현재 YouTube에서 라이브가 아닌 스트림 찾기
            ended_ids = db_live_ids - current_live_ids
            ended_streams = db_live_streams.filter(video_id__in=ended_ids)
            
            for stream in ended_streams:
                stream.mark_as_ended()
                result['ended_streams'].append(stream)
                logger.info(f"라이브 스트림 종료 감지: {stream.title}")
            
            logger.debug(f"채널 {channel.name} 확인 완료: "
                        f"신규 {len(result['new_streams'])}개, "
                        f"종료 {len(result['ended_streams'])}개")
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"채널 {channel.name} 스트림 확인 실패: {e}")
            
        return result
    
    def create_live_stream(self, channel: Channel, stream_info: Dict[str, Any]) -> Optional[LiveStream]:
        """새로운 라이브 스트림 생성 (강화된 중복 감지)"""
        try:
            with transaction.atomic():
                # 강화된 중복 감지
                duplicate_check = duplicate_detection_service.check_stream_duplicate(
                    channel=channel,
                    video_id=stream_info['video_id'],
                    title=stream_info['title'],
                    url=stream_info['url']
                )
                
                if duplicate_check['is_duplicate']:
                    existing_stream = duplicate_check['existing_stream']
                    logger.info(f"중복 스트림 감지: {duplicate_check['reason']}")
                    
                    SystemLog.log('INFO', 'duplicate_detection', 
                                 f"중복 스트림 감지: {stream_info['title'][:100]}",
                                 {
                                     'channel_name': channel.name,
                                     'video_id': stream_info['video_id'],
                                     'duplicate_type': duplicate_check['duplicate_type'],
                                     'confidence': duplicate_check['confidence'],
                                     'reason': duplicate_check['reason'],
                                     'existing_video_id': existing_stream.video_id if existing_stream else None
                                 })
                    
                    return existing_stream
                
                # 새 라이브 스트림 생성
                # 채널의 마지막 라이브 시간 업데이트
                channel.last_live_at = timezone.now()
                channel.save(update_fields=['last_live_at'])
                
                live_stream = LiveStream.objects.create(
                    channel=channel,
                    video_id=stream_info['video_id'],
                    title=stream_info['title'],
                    url=stream_info['url'],
                    thumbnail_url=stream_info.get('thumbnail', ''),
                    status='live',
                    started_at=timezone.now()
                )
                
                logger.info(f"새로운 라이브 스트림 감지: {channel.name} - {live_stream.title}")
                
                SystemLog.log('INFO', 'channel_check', 
                             f"새 라이브 스트림: {live_stream.title}",
                             {
                                 'channel_name': channel.name,
                                 'video_id': live_stream.video_id,
                                 'url': live_stream.url
                             })
                
                return live_stream
                
        except Exception as e:
            logger.error(f"라이브 스트림 생성 실패: {e}")
            SystemLog.log('ERROR', 'channel_check', 
                         f"라이브 스트림 생성 실패: {stream_info.get('title', 'Unknown')}",
                         {'error': str(e), 'stream_info': stream_info})
        
        return None


class StreamEndHandler:
    """라이브 스트림 종료 처리 서비스"""
    
    def process_ended_streams(self) -> Dict[str, Any]:
        """종료된 라이브 스트림들 처리"""
        results = {
            'processed_streams': 0,
            'download_tasks_created': 0,
            'errors': 0
        }
        
        ended_streams = LiveStream.objects.filter(status='ended')
        
        for stream in ended_streams:
            try:
                # 다운로드 작업 생성
                download_created = self.create_download_tasks(stream)
                if download_created:
                    stream.status = 'downloading'
                    stream.save(update_fields=['status'])
                    results['download_tasks_created'] += download_created
                
                results['processed_streams'] += 1
                
            except Exception as e:
                logger.error(f"종료된 스트림 처리 실패 {stream.video_id}: {e}")
                results['errors'] += 1
        
        return results
    
    def create_download_tasks(self, live_stream: LiveStream) -> int:
        """다운로드 작업 생성 (중복 감지 강화)"""
        try:
            with transaction.atomic():
                created_count = 0
                
                # 저화질 다운로드
                low_duplicate_check = duplicate_detection_service.check_download_duplicate(
                    live_stream.video_id, 'low'
                )
                
                if not low_duplicate_check['is_duplicate']:
                    low_download, created = Download.objects.get_or_create(
                        live_stream=live_stream,
                        quality='low',
                        defaults={'status': 'pending'}
                    )
                    if created:
                        created_count += 1
                else:
                    logger.info(f"저화질 다운로드 중복 감지: {low_duplicate_check['reason']}")
                
                # 고화질 다운로드
                high_duplicate_check = duplicate_detection_service.check_download_duplicate(
                    live_stream.video_id, 'high'
                )
                
                if not high_duplicate_check['is_duplicate']:
                    high_download, created = Download.objects.get_or_create(
                        live_stream=live_stream,
                        quality='high',
                        defaults={'status': 'pending'}
                    )
                    if created:
                        created_count += 1
                else:
                    logger.info(f"고화질 다운로드 중복 감지: {high_duplicate_check['reason']}")
                
                if created_count > 0:
                    logger.info(f"다운로드 작업 생성: {live_stream.title} ({created_count}개)")
                else:
                    logger.info(f"다운로드 작업 생성 안함 (중복): {live_stream.title}")
                
                return created_count
                
        except Exception as e:
            logger.error(f"다운로드 작업 생성 실패: {e}")
            
        return 0


class ChannelManagementService:
    """채널 관리 서비스"""
    
    def __init__(self):
        self.youtube_checker = YouTubeLiveChecker()
    
    def add_channel(self, channel_url: str) -> Optional[Channel]:
        """새 채널 추가"""
        try:
            # 채널 정보 추출
            channel_info = self.youtube_checker.get_channel_info(channel_url)
            if not channel_info:
                return None
            
            # 중복 확인
            existing_channel = Channel.objects.filter(
                channel_id=channel_info['channel_id']
            ).first()
            
            if existing_channel:
                return existing_channel
            
            # 새 채널 생성
            channel = Channel.objects.create(
                channel_id=channel_info['channel_id'],
                name=channel_info['channel_name'],
                url=channel_info['channel_url'],
                is_active=True
            )
            
            logger.info(f"새 채널 추가: {channel.name}")
            SystemLog.log('INFO', 'system', f"새 채널 추가: {channel.name}")
            
            return channel
            
        except Exception as e:
            logger.error(f"채널 추가 실패: {e}")
            return None