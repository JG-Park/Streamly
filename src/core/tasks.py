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
from core.models import SystemLog, Settings

# downloads.models는 나중에 임포트 (순환 임포트 방지)
try:
    from downloads.models import Download
except ImportError:
    # 마이그레이션 중일 때는 임포트 실패 허용
    Download = None
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
    """비디오 다운로드 - 완전히 재설계된 버전"""
    # Download 모델 임포트
    from downloads.models import Download
    
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
        
        # yt-dlp 기본 옵션 (최대한 간소화하고 안정적으로)
        ydl_opts = {
            'outtmpl': os.path.join(download_path, f"{filename}.%(ext)s"),
            # 메타데이터 저장
            'writeinfojson': True,
            'writethumbnail': True,
            'writedescription': True,
            # 다운로드 옵션
            'ignoreerrors': False,
            'abort_on_error': False,
            'skip_unavailable_fragments': True,
            'fragment_retries': 10,
            'retries': 10,
            # 로깅
            'quiet': False,
            'no_warnings': False,
            # 후처리 - mp4로 통일
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            # 파일명 안전성
            'restrictfilenames': True,
            'windowsfilenames': True,
        }
        
        # 화질별 포맷 설정 - 매우 유연하게
        if download.quality == 'worst':
            # 저화질: 360p~480p 목표, 실패시 계속 폴백
            ydl_opts['format'] = (
                # 일반적인 360p 포맷들
                '18/'
                # 480p 이하 포맷들
                'best[height<=480]/'
                # 720p 이하 (저화질 대안)
                'best[height<=720]/'
                # 어떤 포맷이든 가장 낮은 것
                'worst/'
                # 마지막 대안: 어떤 것이든
                'best'
            )
        else:
            # 고화질: 4K까지 가능한 최고 화질
            ydl_opts['format'] = (
                # 4K (2160p)
                'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[height<=2160]+bestaudio/'
                # 1440p
                'bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[height<=1440]+bestaudio/'
                # 1080p
                'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[height<=1080]+bestaudio/'
                # 720p
                'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[height<=720]+bestaudio/'
                # 기본 최고 화질
                'bestvideo[ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo+bestaudio/'
                # 최종 폴백
                'best[ext=mp4]/best'
            )
        
        # 다운로드 실행 (에러 처리 강화)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 먼저 정보 추출 시도
                logger.info(f"영상 정보 추출 중: {live_stream.url}")
                info = ydl.extract_info(live_stream.url, download=False)
                
                if not info:
                    raise Exception("영상 정보를 가져올 수 없습니다")
                
                # 포맷 정보 로깅
                formats = info.get('formats', [])
                logger.info(f"사용 가능한 포맷 수: {len(formats)}")
                
                if formats:
                    # 실제 다운로드 실행
                    logger.info(f"다운로드 실행 중...")
                    info = ydl.extract_info(live_stream.url, download=True)
                else:
                    # 포맷이 없으면 기본 설정으로 재시도
                    logger.warning("포맷 정보가 없습니다. 기본 설정으로 시도...")
                    ydl_opts['format'] = None  # 포맷 자동 선택
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                        info = ydl2.extract_info(live_stream.url, download=True)
                        
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"yt-dlp 다운로드 에러: {error_msg}")
            
            # 특정 에러에 대한 처리
            if 'format' in error_msg.lower() or 'requested format' in error_msg.lower():
                # 포맷 에러시 가장 기본적인 설정으로 재시도
                logger.info("포맷 에러 감지, 기본 포맷으로 재시도...")
                simple_opts = ydl_opts.copy()
                simple_opts['format'] = None  # 자동 선택
                
                with yt_dlp.YoutubeDL(simple_opts) as ydl:
                    info = ydl.extract_info(live_stream.url, download=True)
            else:
                raise
            
            # 다운로드된 파일 경로 찾기 (확장자 다양하게 체크)
            downloaded_file = None
            possible_extensions = ['mp4', 'webm', 'mkv', 'flv', 'm4v', 'avi', 'mov']
            
            for ext in possible_extensions:
                potential_file = os.path.join(download_path, f"{filename}.{ext}")
                if os.path.exists(potential_file):
                    downloaded_file = potential_file
                    break
            
            # 파일을 못 찾으면 디렉토리 전체 검색
            if not downloaded_file:
                import glob
                pattern = os.path.join(download_path, f"{filename}.*")
                files = glob.glob(pattern)
                if files:
                    # 비디오 파일 찾기
                    for f in files:
                        if not f.endswith(('.json', '.description', '.jpg', '.png', '.webp')):
                            downloaded_file = f
                            break
            
            if downloaded_file:
                file_size = get_file_size(downloaded_file)
                download.mark_as_completed(downloaded_file, file_size)
                
                logger.info(f"다운로드 완료: {downloaded_file} (크기: {file_size} bytes)")
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
                if download.quality == 'low' or download.quality == 'worst':
                    high_download = Download.objects.filter(
                        live_stream=live_stream,
                        quality__in=['high', 'best'],
                        status='pending'
                    ).first()
                    
                    if high_download:
                        logger.info(f"저화질 완료, 고화질 다운로드 시작: {live_stream.title}")
                        download_video.delay(high_download.id)
                
            else:
                raise Exception(f"다운로드된 파일을 찾을 수 없음: {download_path}/{filename}.*")
    
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
        
        # 재시도 (점진적 백오프)
        if self.request.retries < self.max_retries:
            # 재시도 간격: 2분, 5분, 10분
            retry_delays = [120, 300, 600]
            countdown = retry_delays[min(self.request.retries, len(retry_delays) - 1)]
            
            logger.info(f"다운로드 재시도 ({self.request.retries + 1}/{self.max_retries}), "
                       f"{countdown}초 후 재시도")
            raise self.retry(countdown=countdown)
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
    # Download 모델 임포트
    from downloads.models import Download
    
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
def check_stuck_downloads(self):
    """멈춰있는 다운로드 상태 확인 및 수정
    
    다운로드 중으로 표시되어 있지만 실제로는 완료된 다운로드를 찾아서 수정합니다.
    10분 이상 업데이트가 없는 다운로드를 확인합니다.
    """
    try:
        from django.utils import timezone
        from datetime import timedelta
        import os
        import glob
        
        # 10분 이상 업데이트가 없는 다운로드 중인 항목 찾기
        stuck_time = timezone.now() - timedelta(minutes=10)
        stuck_downloads = Download.objects.filter(
            status='downloading',
            updated_at__lt=stuck_time
        ).select_related('live_stream__channel')
        
        fixed_count = 0
        failed_count = 0
        
        for download in stuck_downloads:
            logger.info(f"멈춘 다운로드 확인: {download.live_stream.title} ({download.quality})")
            
            # 예상 파일 경로 생성
            channel_name = download.live_stream.channel.name
            quality_dir = 'best' if download.quality in ['best', 'high'] else 'worst'
            download_path = f"/app/downloads/{quality_dir}/{channel_name}"
            
            # 파일명 패턴 생성
            safe_title = sanitize_filename(download.live_stream.title)
            timestamp = download.live_stream.started_at.strftime("%Y%m%d_%H%M%S")
            file_pattern = f"{timestamp}_{safe_title}"
            
            # 파일 찾기
            found_file = None
            if os.path.exists(download_path):
                # 다양한 확장자로 시도
                for ext in ['mp4', 'webm', 'mkv', 'flv', 'm4v', 'avi', 'mov']:
                    potential_file = os.path.join(download_path, f"{file_pattern}.{ext}")
                    if os.path.exists(potential_file):
                        found_file = potential_file
                        break
                
                # glob 패턴으로도 시도
                if not found_file:
                    pattern = os.path.join(download_path, f"{file_pattern}.*")
                    files = glob.glob(pattern)
                    for f in files:
                        # 메타데이터 파일 제외
                        if not f.endswith(('.json', '.description', '.jpg', '.png', '.webp', '.part', '.ytdl')):
                            found_file = f
                            break
            
            if found_file:
                # 파일이 존재하면 완료 처리
                file_size = os.path.getsize(found_file)
                download.mark_as_completed(found_file, file_size)
                fixed_count += 1
                logger.info(f"다운로드 상태 수정 완료: {download.live_stream.title} - {found_file}")
                SystemLog.log('INFO', 'download_fix', 
                             f"멈춘 다운로드 상태 수정: {download.live_stream.title}",
                             {'file_path': found_file, 'file_size': file_size})
            else:
                # 파일이 없고 너무 오래되었으면 실패 처리
                if download.updated_at < timezone.now() - timedelta(hours=1):
                    download.mark_as_failed("다운로드가 중단됨 (파일 없음)")
                    failed_count += 1
                    logger.warning(f"다운로드 실패 처리: {download.live_stream.title}")
                else:
                    logger.info(f"다운로드 진행 중으로 유지: {download.live_stream.title}")
        
        if fixed_count > 0 or failed_count > 0:
            SystemLog.log('INFO', 'download_fix', 
                         f"멈춘 다운로드 확인 완료: 수정 {fixed_count}개, 실패 {failed_count}개")
        
        return {
            'checked': stuck_downloads.count(),
            'fixed': fixed_count,
            'failed': failed_count
        }
        
    except Exception as e:
        logger.error(f"멈춘 다운로드 확인 실패: {e}")
        SystemLog.log('ERROR', 'download_fix', f"멈춘 다운로드 확인 실패: {e}")
        raise


@shared_task(bind=True)
def retry_failed_stream_downloads(self):
    """종료 후 실패한 스트림 다운로드 재시도
    
    종료 후 1시간 이내의 스트림을 10초 간격으로 재시도합니다.
    비공개에서 공개로 전환된 영상을 다운로드할 수 있도록 합니다.
    """
    try:
        from django.utils import timezone
        from datetime import timedelta
        import yt_dlp
        
        # 1시간 이내에 종료된 스트림 중 다운로드가 실패하거나 시작되지 않은 것
        one_hour_ago = timezone.now() - timedelta(hours=1)
        
        failed_streams = LiveStream.objects.filter(
            status='ended',
            ended_at__gte=one_hour_ago,
            retry_enabled=True,
            retry_count__lt=360  # 최대 360회 (1시간 / 10초)
        ).exclude(
            downloads__status__in=['completed', 'downloading']
        )
        
        checked_count = 0
        retry_started = 0
        
        for stream in failed_streams:
            logger.info(f"재시도 확인: {stream.title} (시도 {stream.retry_count}/360)")
            
            # 마지막 재시도로부터 10초 경과 확인
            if stream.last_retry_at:
                time_since_last = timezone.now() - stream.last_retry_at
                if time_since_last.seconds < 10:
                    continue
            
            # 영상 접근 가능 여부 확인
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(stream.url, download=False)
                    
                    # 비공개 상태 확인
                    is_private = info.get('availability') == 'private'
                    is_unavailable = info.get('availability') == 'unavailable'
                    
                    if not is_private and not is_unavailable:
                        # 다운로드 가능한 상태
                        logger.info(f"다운로드 가능 상태로 전환됨: {stream.title}")
                        
                        # 다운로드 작업 생성
                        from downloads.models import Download
                        from core.services import StreamEndHandler
                        
                        handler = StreamEndHandler()
                        created_count = handler.create_download_tasks(stream)
                        
                        if created_count > 0:
                            # 다운로드 시작
                            low_download = Download.objects.filter(
                                live_stream=stream,
                                quality__in=['worst', 'low'],
                                status='pending'
                            ).first()
                            
                            if low_download:
                                download_video.delay(low_download.id)
                                retry_started += 1
                                logger.info(f"재시도 다운로드 시작: {stream.title}")
                                
                                # 재시도 비활성화
                                stream.retry_enabled = False
                                stream.save(update_fields=['retry_enabled'])
                        
                    else:
                        logger.debug(f"아직 비공개/접근불가: {stream.title}")
                        
            except Exception as e:
                logger.debug(f"영상 확인 실패 {stream.title}: {e}")
            
            # 재시도 횟수 업데이트
            stream.retry_count += 1
            stream.last_retry_at = timezone.now()
            
            # 최대 재시도 횟수 도달 시 비활성화
            if stream.retry_count >= 360:
                stream.retry_enabled = False
                logger.info(f"최대 재시도 횟수 도달, 재시도 중단: {stream.title}")
            
            stream.save(update_fields=['retry_count', 'last_retry_at', 'retry_enabled'])
            checked_count += 1
        
        if checked_count > 0:
            SystemLog.log('INFO', 'retry_download',
                         f"실패한 스트림 재시도: 확인 {checked_count}개, 시작 {retry_started}개")
        
        return {
            'checked': checked_count,
            'started': retry_started
        }
        
    except Exception as e:
        logger.error(f"스트림 재시도 확인 실패: {e}")
        SystemLog.log('ERROR', 'retry_download', f"스트림 재시도 확인 실패: {e}")
        raise


@shared_task(bind=True)
def download_manual_video(self, manual_download_id):
    """수동 YouTube 영상 다운로드
    
    ManualDownload 모델의 영상을 다운로드합니다.
    """
    try:
        from downloads.models_manual import ManualDownload
        download = ManualDownload.objects.get(id=manual_download_id)
        
        if download.status != 'pending':
            logger.warning(f"잘못된 다운로드 상태: {download.status}")
            return {'status': 'invalid_status'}
        
        # 다운로드 시작
        download.start_download()
        
        # 다운로드 경로 설정
        download_dir = os.path.join(
            settings.MEDIA_ROOT, 'manual_downloads',
            datetime.now().strftime('%Y%m')
        )
        os.makedirs(download_dir, exist_ok=True)
        
        # 파일명 생성 (특수문자 제거)
        import re
        safe_title = re.sub(r'[^\w\s-]', '', download.title or 'video')
        safe_title = re.sub(r'[-\s]+', '-', safe_title)[:100]
        file_name = f"{download.video_id}_{safe_title}"
        file_path = os.path.join(download_dir, file_name)
        
        # yt-dlp 옵션 설정
        ydl_opts = {
            'format': download.quality if download.quality != 'best' else 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': f'{file_path}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [lambda d: self._update_progress(download, d)],
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }] if download.quality == 'best' else [],
        }
        
        # 다운로드 실행
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(download.url, download=True)
            
            # 실제 파일 경로 찾기
            actual_file = None
            for ext in ['mp4', 'webm', 'mkv', 'avi', 'mov']:
                test_path = f'{file_path}.{ext}'
                if os.path.exists(test_path):
                    actual_file = test_path
                    break
            
            if not actual_file:
                raise Exception("다운로드된 파일을 찾을 수 없습니다")
            
            # 파일 정보 업데이트
            file_size = os.path.getsize(actual_file)
            
            # 비디오 정보 추출
            resolution = None
            video_codec = None
            audio_codec = None
            
            if 'formats' in info and info['formats']:
                best_format = info['formats'][-1]
                resolution = best_format.get('resolution') or f"{best_format.get('width', '?')}x{best_format.get('height', '?')}"
                video_codec = best_format.get('vcodec')
                audio_codec = best_format.get('acodec')
            
            # 다운로드 완료
            download.complete_download(
                file_path=actual_file,
                file_size=file_size,
                resolution=resolution,
                video_codec=video_codec,
                audio_codec=audio_codec
            )
            
            logger.info(f"수동 다운로드 완료: {download.title}")
            SystemLog.log('INFO', 'manual_download',
                         f"수동 다운로드 완료: {download.title}",
                         {'download_id': download.id, 'file_size': file_size})
            
            return {
                'status': 'completed',
                'file_path': actual_file,
                'file_size': file_size
            }
            
    except ManualDownload.DoesNotExist:
        logger.error(f"존재하지 않는 다운로드: {manual_download_id}")
        return {'status': 'not_found'}
    except Exception as e:
        logger.error(f"수동 다운로드 실패: {e}")
        if 'download' in locals():
            download.fail_download(str(e))
        SystemLog.log('ERROR', 'manual_download',
                     f"수동 다운로드 실패: {str(e)}",
                     {'download_id': manual_download_id})
        return {'status': 'error', 'error': str(e)}
    
    def _update_progress(self, download, d):
        """다운로드 진행률 업데이트"""
        if d['status'] == 'downloading':
            if 'total_bytes' in d and d['total_bytes'] > 0:
                progress = int(d['downloaded_bytes'] * 100 / d['total_bytes'])
                download.progress = min(progress, 99)
                download.save(update_fields=['progress'])


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
        download.started_at = None
        download.save(update_fields=['status', 'error_message', 'started_at'])
        
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