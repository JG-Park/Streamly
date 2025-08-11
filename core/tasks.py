"""
Celery 태스크들
"""

import os
import logging
import yt_dlp
from datetime import datetime, timedelta
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from channels.models import Channel, LiveStream
from downloads.models import Download
from core.models import SystemLog, Settings
from core.services import ChannelMonitorService, StreamEndHandler
from core.utils import create_download_path, get_file_size, sanitize_filename

logger = logging.getLogger('streamly')


@shared_task(bind=True, max_retries=3)
def add_channel_async(self, channel_url):
    """채널 추가 비동기 처리"""
    try:
        from channels.models import Channel
        from core.services import ChannelManagementService
        from core.models import SystemLog
        
        # 채널 관리 서비스로 채널 정보 가져오기
        service = ChannelManagementService()
        channel_info = service.youtube_checker.get_channel_info(channel_url)
        
        if not channel_info:
            SystemLog.log('ERROR', 'channel', 
                         f"채널 정보를 가져올 수 없음: {channel_url}")
            return None
        
        # 채널 업데이트 또는 생성
        channel, created = Channel.objects.update_or_create(
            channel_id=channel_info['channel_id'],
            defaults={
                'name': channel_info['channel_name'],
                'url': channel_info['channel_url'],
                'is_active': True,
                'check_interval_minutes': 1,
            }
        )
        
        if created:
            SystemLog.log('INFO', 'channel', 
                         f"새 채널 추가됨: {channel.name}",
                         {'channel_id': channel.channel_id})
        else:
            SystemLog.log('INFO', 'channel', 
                         f"기존 채널 정보 업데이트: {channel.name}",
                         {'channel_id': channel.channel_id})
        
        return channel.id
        
    except Exception as e:
        logger.error(f"채널 추가 실패: {channel_url}, 에러: {e}")
        SystemLog.log('ERROR', 'channel', 
                     f"채널 추가 실패: {channel_url}",
                     {'error': str(e)})
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True)
def check_all_channels(self):
    """모든 활성 채널의 라이브 스트림 확인"""
    try:
        service = ChannelMonitorService()
        results = service.check_all_active_channels()
        
        logger.info(f"채널 모니터링 완료: {results}")
        
        # 새로운 라이브 스트림에 대한 알림 전송
        for channel_result in results['channel_results']:
            for stream in channel_result.get('new_streams', []):
                if hasattr(stream, 'id'):
                    send_live_notification.delay(stream.id)
        
        # 종료된 라이브 스트림에 대한 다운로드 시작
        for channel_result in results['channel_results']:
            for stream in channel_result.get('ended_streams', []):
                if hasattr(stream, 'id'):
                    process_ended_stream.delay(stream.id)
        
        # 결과를 직렬화 가능한 형태로 변환
        serializable_results = {
            'checked_channels': results.get('checked_channels', 0),
            'new_streams': results.get('new_streams', 0),
            'ended_streams': results.get('ended_streams', 0),
            'errors': results.get('errors', 0)
        }
        
        return serializable_results
        
    except Exception as e:
        logger.error(f"채널 확인 태스크 실패: {e}")
        SystemLog.log('ERROR', 'channel_check', f"채널 확인 태스크 실패: {e}")
        raise


@shared_task(bind=True)
def check_channel_live_streams(self, channel_id):
    """특정 채널의 라이브 스트림 확인"""
    try:
        channel = Channel.objects.get(id=channel_id, is_active=True)
        service = ChannelMonitorService()
        
        # 단일 채널 확인
        result = service.check_channel_streams(channel)
        
        logger.info(f"채널 '{channel.name}' 확인 완료: {result}")
        
        # 새로운 라이브 스트림에 대한 알림 전송
        for stream in result.get('new_streams', []):
            if hasattr(stream, 'id'):
                send_live_notification.delay(stream.id)
        
        # 종료된 라이브 스트림에 대한 다운로드 시작
        for stream in result.get('ended_streams', []):
            if hasattr(stream, 'id'):
                process_ended_stream.delay(stream.id)
        
        # 결과를 직렬화 가능한 형태로 변환
        serializable_result = {
            'channel_id': channel_id,
            'channel_name': result.get('channel', {}).get('name', ''),
            'new_streams_count': len(result.get('new_streams', [])),
            'ended_streams_count': len(result.get('ended_streams', [])),
            'error': result.get('error')
        }
        
        return serializable_result
        
    except Channel.DoesNotExist:
        logger.error(f"채널 ID {channel_id}를 찾을 수 없습니다.")
        return {'error': 'Channel not found'}
    except Exception as e:
        logger.error(f"채널 {channel_id} 확인 태스크 실패: {e}")
        SystemLog.log('ERROR', 'channel_check', f"채널 {channel_id} 확인 실패: {e}")
        raise


@shared_task(bind=True)
def check_single_channel(self, channel_id):
    """단일 채널 즉시 체크 (API에서 호출용)"""
    try:
        channel = Channel.objects.get(id=channel_id)
        service = ChannelMonitorService()
        
        logger.info(f"채널 '{channel.name}' 즉시 체크 시작")
        SystemLog.log('INFO', 'channel_check', 
                     f"채널 즉시 체크 시작: {channel.name}",
                     {'channel_id': channel.channel_id})
        
        # 단일 채널 확인
        result = service.check_channel_streams(channel)
        
        # 새로운 라이브 스트림에 대한 알림 전송
        for stream in result.get('new_streams', []):
            if hasattr(stream, 'id'):
                send_live_notification.delay(stream.id)
                logger.info(f"새 라이브 발견: {stream.title}")
        
        # 종료된 라이브 스트림에 대한 다운로드 시작
        for stream in result.get('ended_streams', []):
            if hasattr(stream, 'id'):
                process_ended_stream.delay(stream.id)
                logger.info(f"종료된 라이브 발견: {stream.title}")
        
        # 마지막 체크 시간 업데이트
        channel.update_last_checked()
        
        logger.info(f"채널 '{channel.name}' 즉시 체크 완료: "
                   f"신규 {len(result.get('new_streams', []))}개, "
                   f"종료 {len(result.get('ended_streams', []))}개")
        
        SystemLog.log('INFO', 'channel_check',
                     f"채널 즉시 체크 완료: {channel.name}",
                     {
                         'channel_id': channel.channel_id,
                         'new_streams': len(result.get('new_streams', [])),
                         'ended_streams': len(result.get('ended_streams', []))
                     })
        
        # 결과를 직렬화 가능한 형태로 변환
        serializable_result = {
            'channel_id': channel_id,
            'channel_name': channel.name,
            'channel_url': channel.url,
            'new_streams_count': len(result.get('new_streams', [])),
            'ended_streams_count': len(result.get('ended_streams', [])),
            'current_live_count': LiveStream.objects.filter(
                channel=channel, 
                status='live'
            ).count(),
            'error': result.get('error'),
            'checked_at': timezone.now().isoformat()
        }
        
        return serializable_result
        
    except Channel.DoesNotExist:
        logger.error(f"채널 ID {channel_id}를 찾을 수 없습니다.")
        return {'error': f'Channel {channel_id} not found'}
    except Exception as e:
        logger.error(f"채널 {channel_id} 즉시 체크 실패: {e}")
        SystemLog.log('ERROR', 'channel_check', 
                     f"채널 즉시 체크 실패: {channel_id}",
                     {'error': str(e)})
        raise


@shared_task(bind=True)
def process_ended_streams(self):
    """종료된 라이브 스트림 처리"""
    try:
        handler = StreamEndHandler()
        results = handler.process_ended_streams()
        
        logger.info(f"종료된 스트림 처리 완료: {results}")
        return results
        
    except Exception as e:
        logger.error(f"종료된 스트림 처리 태스크 실패: {e}")
        SystemLog.log('ERROR', 'system', f"종료된 스트림 처리 실패: {e}")
        raise


@shared_task(bind=True)
def process_ended_stream(self, stream_id):
    """개별 종료된 라이브 스트림 처리"""
    try:
        stream = LiveStream.objects.get(id=stream_id)
        handler = StreamEndHandler()
        
        # 다운로드 작업 생성
        created_count = handler.create_download_tasks(stream)
        
        if created_count > 0:
            stream.status = 'downloading'
            stream.save(update_fields=['status'])
            
            # 저화질 다운로드를 먼저 시작
            low_download = Download.objects.filter(
                live_stream=stream, 
                quality='low', 
                status='pending'
            ).first()
            
            if low_download:
                # 저화질 다운로드 시작
                download_video.delay(low_download.id)
                logger.info(f"저화질 다운로드 시작: {stream.title}")
            else:
                # 저화질이 없으면 고화질 다운로드 시작
                high_download = Download.objects.filter(
                    live_stream=stream, 
                    quality='high', 
                    status='pending'
                ).first()
                if high_download:
                    download_video.delay(high_download.id)
                    logger.info(f"고화질 다운로드 시작: {stream.title}")
        
        return f"다운로드 작업 {created_count}개 생성됨"
        
    except LiveStream.DoesNotExist:
        logger.error(f"존재하지 않는 라이브 스트림: {stream_id}")
    except Exception as e:
        logger.error(f"스트림 처리 실패 {stream_id}: {e}")
        raise


@shared_task(bind=True, max_retries=3)
def download_video(self, download_id):
    """비디오 다운로드"""
    try:
        download = Download.objects.select_related('live_stream__channel').get(id=download_id)
        live_stream = download.live_stream
        channel = live_stream.channel
        
        # 다운로드 시작 처리
        download.mark_as_downloading()
        
        logger.info(f"다운로드 시작: {live_stream.title} ({download.get_quality_display()})")
        
        # 다운로드 경로 설정
        download_path = create_download_path(channel.name, download.quality)
        
        # 파일명 생성
        safe_title = sanitize_filename(live_stream.title)
        timestamp = live_stream.started_at.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{safe_title}"
        
        # yt-dlp 옵션 설정 (속도 최적화)
        ydl_opts = {
            'outtmpl': os.path.join(download_path, f"{filename}.%(ext)s"),
            'writeinfojson': True,
            'writethumbnail': True,
            'writedescription': True,
            # 속도 최적화 옵션
            'concurrent_fragment_downloads': 8,  # 동시 프래그먼트 다운로드 수 증가
            'http_chunk_size': 10485760,  # 10MB 청크 크기
            'retries': 10,  # 재시도 횟수
            'fragment_retries': 10,  # 프래그먼트 재시도
            'skip_unavailable_fragments': True,  # 사용 불가능한 프래그먼트 건너뛰기
            'keepvideo': False,  # 임시 파일 삭제
            'buffersize': 1024 * 64,  # 64KB 버퍼로 증가
            'noresizebuffer': False,
            'continuedl': True,  # 다운로드 이어받기
            'noprogress': False,  # 진행률 표시
            'ratelimit': None,  # 속도 제한 없음
            'throttledratelimit': None,  # 스로틀 제한 없음
            # aria2c 외부 다운로더 사용 (더 빠른 다운로드)
            'external_downloader': 'aria2c',
            'external_downloader_args': [
                '-x', '16',  # 16개 연결 사용
                '-s', '16',  # 16개 분할 다운로드
                '-k', '1M',  # 1MB 청크 크기
                '--max-connection-per-server=16',  # 서버당 최대 연결
                '--min-split-size=1M',  # 최소 분할 크기
                '--split=16',  # 16개로 분할
                '--max-concurrent-downloads=5',  # 동시 다운로드
                '--continue=true',  # 이어받기
                '--auto-file-renaming=false',  # 자동 파일명 변경 비활성화
            ],
        }
        
        # 화질별 포맷 설정 (더 효율적인 포맷 선택)
        if download.quality == 'low':
            # 저화질: 360p 이하, 빠른 다운로드
            ydl_opts['format'] = 'worst[height<=360]/worst'
        else:
            # 고화질: 1080p 우선, 없으면 최고 화질
            ydl_opts['format'] = 'best[height<=1080]/best'
        
        # 다운로드 실행
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(live_stream.url, download=True)
            
            # 다운로드된 파일 경로 찾기
            downloaded_file = None
            for ext in ['mp4', 'webm', 'mkv', 'flv']:
                potential_file = os.path.join(download_path, f"{filename}.{ext}")
                if os.path.exists(potential_file):
                    downloaded_file = potential_file
                    break
            
            if downloaded_file:
                file_size = get_file_size(downloaded_file)
                download.mark_as_completed(downloaded_file, file_size)
                
                logger.info(f"다운로드 완료: {downloaded_file}")
                SystemLog.log('INFO', 'download', 
                             f"다운로드 완료: {live_stream.title} ({download.get_quality_display()})",
                             {
                                 'file_path': downloaded_file,
                                 'file_size': file_size,
                                 'channel_name': channel.name
                             })
                
                # 다운로드 완료 알림 전송
                send_download_notification.delay(download.id)
                
                # 저화질 다운로드 완료 시 고화질 다운로드 시작
                if download.quality == 'low':
                    high_download = Download.objects.filter(
                        live_stream=live_stream,
                        quality='high',
                        status='pending'
                    ).first()
                    
                    if high_download:
                        logger.info(f"저화질 완료, 고화질 다운로드 시작: {live_stream.title}")
                        download_video.delay(high_download.id)
                
            else:
                raise Exception("다운로드된 파일을 찾을 수 없음")
    
    except Download.DoesNotExist:
        logger.error(f"존재하지 않는 다운로드: {download_id}")
    except Exception as e:
        logger.error(f"다운로드 실패 {download_id}: {e}")
        
        try:
            download = Download.objects.get(id=download_id)
            download.mark_as_failed(str(e))
            SystemLog.log('ERROR', 'download', 
                         f"다운로드 실패: {download.live_stream.title}",
                         {'error': str(e), 'download_id': download_id})
        except:
            pass
        
        # 재시도
        if self.request.retries < self.max_retries:
            logger.info(f"다운로드 재시도 ({self.request.retries + 1}/{self.max_retries})")
            raise self.retry(countdown=60 * (self.request.retries + 1))
        else:
            logger.error(f"다운로드 최종 실패: {download_id}")


@shared_task(bind=True)
def send_live_notification(self, stream_id):
    """라이브 시작 알림 전송"""
    try:
        from .telegram_service import TelegramService
        
        stream = LiveStream.objects.select_related('channel').get(id=stream_id)
        
        if stream.notification_sent:
            return "이미 알림 전송됨"
        
        telegram = TelegramService()
        message = f"🔴 라이브 시작!\n\n" \
                 f"📺 채널: {stream.channel.name}\n" \
                 f"📹 제목: {stream.title}\n" \
                 f"🔗 URL: {stream.url}"
        
        success = telegram.send_message(message)
        
        if success:
            stream.notification_sent = True
            stream.save(update_fields=['notification_sent'])
            logger.info(f"라이브 시작 알림 전송: {stream.title}")
        
        return "알림 전송 완료" if success else "알림 전송 실패"
        
    except LiveStream.DoesNotExist:
        logger.error(f"존재하지 않는 라이브 스트림: {stream_id}")
    except Exception as e:
        logger.error(f"라이브 알림 전송 실패: {e}")
        raise


@shared_task(bind=True)
def send_download_notification(self, download_id):
    """다운로드 완료 알림 전송"""
    try:
        from .telegram_service import TelegramService
        
        download = Download.objects.select_related('live_stream__channel').get(id=download_id)
        live_stream = download.live_stream
        
        telegram = TelegramService()
        
        # 파일 크기 포맷팅
        file_size_str = None
        if download.file_size:
            from core.utils import format_file_size
            file_size_str = format_file_size(download.file_size)
        
        # 텔레그램 알림 전송
        success = telegram.send_download_complete_notification(
            channel_name=live_stream.channel.name,
            title=live_stream.title,
            quality=download.get_quality_display(),
            file_size=file_size_str
        )
        logger.info(f"다운로드 완료 알림 전송: {live_stream.title}")
        
    except Download.DoesNotExist:
        logger.error(f"존재하지 않는 다운로드: {download_id}")
    except Exception as e:
        logger.error(f"다운로드 알림 전송 실패: {e}")


@shared_task(bind=True)
def cleanup_old_downloads(self):
    """오래된 다운로드 파일 정리"""
    try:
        now = timezone.now()
        old_downloads = Download.objects.filter(
            delete_after__lt=now,
            status='completed'
        )
        
        deleted_count = 0
        freed_space = 0
        
        for download in old_downloads:
            if download.file_path and os.path.exists(download.file_path):
                try:
                    file_size = download.file_size or get_file_size(download.file_path) or 0
                    os.remove(download.file_path)
                    freed_space += file_size
                    deleted_count += 1
                    
                    # 관련 파일들도 삭제 (썸네일, 정보 파일 등)
                    base_path = os.path.splitext(download.file_path)[0]
                    for ext in ['.info.json', '.description', '.jpg', '.png', '.webp']:
                        related_file = base_path + ext
                        if os.path.exists(related_file):
                            os.remove(related_file)
                    
                except OSError as e:
                    logger.error(f"파일 삭제 실패: {download.file_path}, 에러: {e}")
        
        # 데이터베이스에서도 삭제
        deleted_db_count = old_downloads.delete()[0]
        
        from core.utils import format_file_size
        logger.info(f"정리 완료: 파일 {deleted_count}개, DB 레코드 {deleted_db_count}개, "
                   f"확보된 공간: {format_file_size(freed_space)}")
        
        SystemLog.log('INFO', 'cleanup', 
                     f"다운로드 파일 정리 완료: {deleted_count}개 파일 삭제",
                     {
                         'deleted_files': deleted_count,
                         'deleted_records': deleted_db_count,
                         'freed_space_bytes': freed_space
                     })
        
        return {
            'deleted_files': deleted_count,
            'deleted_records': deleted_db_count,
            'freed_space_bytes': freed_space
        }
        
    except Exception as e:
        logger.error(f"다운로드 정리 실패: {e}")
        SystemLog.log('ERROR', 'cleanup', f"다운로드 정리 실패: {e}")
        raise


@shared_task(bind=True)
def cleanup_old_logs(self):
    """오래된 로그 정리"""
    try:
        # 30일 이상된 로그 삭제
        cutoff_date = timezone.now() - timedelta(days=30)
        deleted_count = SystemLog.objects.filter(
            created_at__lt=cutoff_date
        ).delete()[0]
        
        logger.info(f"오래된 로그 정리: {deleted_count}개 삭제")
        
        return {'deleted_logs': deleted_count}
        
    except Exception as e:
        logger.error(f"로그 정리 실패: {e}")
        raise


@shared_task(bind=True)
def process_pending_downloads(self):
    """대기 중인 다운로드 처리
    
    주기적으로 실행되어 pending 상태의 다운로드를 처리합니다.
    저화질 다운로드를 먼저 시작하고, 완료 후 고화질을 시작합니다.
    """
    try:
        # 대기 중인 다운로드 찾기 (오래된 순으로 정렬)
        pending_downloads = Download.objects.filter(
            status='pending'
        ).select_related('live_stream__channel').order_by('created_at')
        
        processed_count = 0
        started_downloads = []
        
        for download in pending_downloads:
            # 저화질 다운로드 우선 처리
            if download.quality == 'low':
                # 같은 스트림의 고화질이 진행 중인지 확인
                high_download_in_progress = Download.objects.filter(
                    live_stream=download.live_stream,
                    quality='high',
                    status='downloading'
                ).exists()
                
                if not high_download_in_progress:
                    # 다운로드 시작
                    download_video.delay(download.id)
                    started_downloads.append({
                        'id': download.id,
                        'title': download.live_stream.title,
                        'quality': download.get_quality_display(),
                        'channel': download.live_stream.channel.name
                    })
                    processed_count += 1
                    logger.info(f"저화질 다운로드 시작: {download.live_stream.title}")
            
            # 고화질 다운로드는 저화질이 없거나 완료된 경우만 처리
            elif download.quality == 'high':
                low_download = Download.objects.filter(
                    live_stream=download.live_stream,
                    quality='low'
                ).first()
                
                # 저화질이 없거나 완료/실패인 경우
                if not low_download or low_download.status in ['completed', 'failed']:
                    download_video.delay(download.id)
                    started_downloads.append({
                        'id': download.id,
                        'title': download.live_stream.title,
                        'quality': download.get_quality_display(),
                        'channel': download.live_stream.channel.name
                    })
                    processed_count += 1
                    logger.info(f"고화질 다운로드 시작: {download.live_stream.title}")
        
        if processed_count > 0:
            SystemLog.log('INFO', 'download', 
                         f"대기 중 다운로드 처리: {processed_count}개 시작",
                         {'started_downloads': started_downloads})
        
        logger.info(f"대기 중 다운로드 처리 완료: {processed_count}개 시작")
        
        return {
            'processed_count': processed_count,
            'started_downloads': started_downloads
        }
        
    except Exception as e:
        logger.error(f"대기 중 다운로드 처리 실패: {e}")
        SystemLog.log('ERROR', 'download', f"대기 중 다운로드 처리 실패: {e}")
        raise


@shared_task(bind=True)
def force_start_download(self, download_id):
    """강제로 다운로드 시작
    
    상태에 관계없이 다운로드를 강제로 시작합니다.
    """
    try:
        download = Download.objects.select_related('live_stream__channel').get(id=download_id)
        
        # 이미 완료된 경우는 건너뛰기
        if download.status == 'completed':
            logger.info(f"이미 완료된 다운로드: {download.live_stream.title}")
            return {'status': 'already_completed'}
        
        # 상태를 pending으로 초기화
        download.status = 'pending'
        download.error_message = None
        download.download_started_at = None
        download.save(update_fields=['status', 'error_message', 'download_started_at'])
        
        # 다운로드 시작
        download_video.delay(download.id)
        
        logger.info(f"강제 다운로드 시작: {download.live_stream.title} ({download.get_quality_display()})")
        
        SystemLog.log('INFO', 'download', 
                     f"강제 다운로드 시작: {download.live_stream.title}",
                     {
                         'download_id': download.id,
                         'quality': download.quality,
                         'channel': download.live_stream.channel.name
                     })
        
        return {
            'status': 'started',
            'download_id': download.id,
            'title': download.live_stream.title,
            'quality': download.get_quality_display()
        }
        
    except Download.DoesNotExist:
        logger.error(f"존재하지 않는 다운로드: {download_id}")
        return {'status': 'not_found'}
    except Exception as e:
        logger.error(f"강제 다운로드 시작 실패: {e}")
        return {'status': 'error', 'error': str(e)}