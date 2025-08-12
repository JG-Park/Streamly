"""
대시보드 뷰
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
import sys
import django
import yt_dlp
import shutil
import os

from channels.models import Channel, LiveStream
from core.models import SystemLog, Settings
from core.utils import format_file_size

# downloads.models는 나중에 임포트 (순환 임포트 방지)
try:
    from downloads.models import Download
except ImportError:
    # 마이그레이션 중일 때는 임포트 실패 허용
    Download = None


@login_required
def dashboard_index(request):
    """메인 대시보드"""
    # downloads 모듈 동적 임포트
    global Download
    if Download is None:
        from downloads.models import Download
    
    # 통계 데이터
    stats = {
        'total_channels': Channel.objects.count(),
        'active_channels': Channel.objects.filter(is_active=True).count(),
        'total_streams': LiveStream.objects.count(),
        'live_streams': LiveStream.objects.filter(status='live').count(),
    }
    
    # 다운로드 통계
    download_stats = Download.objects.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='completed')),
        pending=Count('id', filter=Q(status='pending')),
        downloading=Count('id', filter=Q(status='downloading')),
        failed=Count('id', filter=Q(status='failed')),
        total_size=Sum('file_size', filter=Q(status='completed'))
    )
    
    stats.update(download_stats)
    stats['total_storage_used'] = format_file_size(download_stats['total_size'] or 0)
    
    # 최근 활동
    recent_activities = []
    
    # 최근 라이브 스트림
    recent_streams = LiveStream.objects.select_related('channel').order_by('-started_at')[:5]
    for stream in recent_streams:
        recent_activities.append({
            'type': 'live_stream',
            'icon': 'play-circle',
            'message': f"{stream.channel.name}에서 라이브 시작",
            'title': stream.title,
            'timestamp': stream.started_at,
            'status': stream.status
        })
    
    # 최근 다운로드
    recent_downloads = Download.objects.select_related('live_stream__channel').order_by('-created_at')[:5]
    for download in recent_downloads:
        icon_map = {
            'completed': 'check-circle',
            'failed': 'x-circle',
            'downloading': 'download',
            'pending': 'clock'
        }
        recent_activities.append({
            'type': 'download',
            'icon': icon_map.get(download.status, 'download'),
            'message': f"다운로드 {download.get_status_display()}",
            'title': f"{download.live_stream.title} ({download.get_quality_display()})",
            'timestamp': download.created_at,
            'status': download.status
        })
    
    # 시간순 정렬
    recent_activities.sort(key=lambda x: x['timestamp'], reverse=True)
    recent_activities = recent_activities[:10]
    
    # 활성 채널 목록
    active_channels = Channel.objects.filter(is_active=True).order_by('name')[:10]
    
    # 현재 라이브 중인 스트림
    live_streams = LiveStream.objects.filter(status='live').select_related('channel').order_by('-started_at')
    
    # 최근 스트림
    recent_streams = LiveStream.objects.select_related('channel').order_by('-started_at')[:10]
    
    context = {
        'stats': stats,
        'recent_activities': recent_activities,
        'recent_streams': recent_streams,
        'active_channels': active_channels,
        'live_streams': live_streams,
    }
    
    return render(request, 'dashboard/index.html', context)


@login_required
def channels_page(request):
    """채널 관리 페이지"""
    channels = Channel.objects.all().order_by('-is_active', 'name')
    
    # 각 채널의 통계 추가
    for channel in channels:
        channel.stream_count = channel.live_streams.count()
        channel.last_stream = channel.live_streams.order_by('-started_at').first()
    
    context = {
        'channels': channels,
        'page_title': '채널 관리',
    }
    
    return render(request, 'dashboard/channels.html', context)


@login_required
def streams_page(request):
    """라이브 스트림 페이지"""
    streams = LiveStream.objects.select_related('channel').prefetch_related('downloads')
    streams = streams.order_by('-started_at')
    
    # 페이지네이션
    paginator = Paginator(streams, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # 현재 라이브 중인 스트림
    live_streams = streams.filter(status='live')
    
    # 채널 목록 (필터용)
    channels = Channel.objects.filter(is_active=True).order_by('name')
    
    context = {
        'streams': page_obj.object_list,
        'page_obj': page_obj,
        'live_streams': live_streams,
        'channels': channels,
        'page_title': '라이브 스트림',
    }
    
    return render(request, 'dashboard/streams.html', context)


@login_required
def downloads_page(request):
    """다운로드 관리 페이지"""
    # downloads 모듈 동적 임포트
    global Download
    if Download is None:
        from downloads.models import Download
    
    downloads = Download.objects.select_related('live_stream__channel')
    downloads = downloads.order_by('-created_at')
    
    # 스트림 필터
    stream_id = request.GET.get('stream')
    if stream_id:
        downloads = downloads.filter(live_stream_id=stream_id)
    
    # 페이지네이션
    paginator = Paginator(downloads, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # 통계
    all_downloads = Download.objects.all()
    stats = {
        'total': all_downloads.count(),
        'pending': all_downloads.filter(status='pending').count(),
        'downloading': all_downloads.filter(status='downloading').count(),
        'completed': all_downloads.filter(status='completed').count(),
        'failed': all_downloads.filter(status='failed').count(),
    }
    
    # 저장 공간 사용량
    total_size = all_downloads.filter(status='completed').aggregate(
        total=Sum('file_size')
    )['total'] or 0
    stats['total_size'] = format_file_size(total_size)
    
    # 영상별로 그룹화
    stream_downloads = {}
    for download in downloads:
        stream_id = download.live_stream_id
        if stream_id not in stream_downloads:
            stream_downloads[stream_id] = {
                'stream': download.live_stream,
                'channel': download.live_stream.channel,
                'high_quality': None,
                'low_quality': None
            }
        
        # 100% 완료인데 다운로드 중인 경우 자동 수정
        if download.progress == 100 and download.status == 'downloading':
            if download.file_path and os.path.exists(download.file_path):
                download.status = 'completed'
                download.save(update_fields=['status'])
        
        # 품질별로 분류
        download_info = {
            'download': download,
            'file_size_display': format_file_size(download.file_size) if download.file_size else '-',
            'status_display': download.get_status_display(),
            'resolution': download.resolution or '미확인'
        }
        
        if download.quality in ['best', 'high']:
            stream_downloads[stream_id]['high_quality'] = download_info
        else:  # worst, low
            stream_downloads[stream_id]['low_quality'] = download_info
    
    # 페이지네이션을 위해 리스트로 변환 (최신순)
    stream_downloads_list = sorted(
        stream_downloads.values(), 
        key=lambda x: x['stream'].started_at or x['stream'].created_at,
        reverse=True
    )
    
    # 페이지네이션
    from django.core.paginator import Paginator
    paginator = Paginator(stream_downloads_list, 20)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'stream_downloads': page_obj.object_list,
        'page_obj': page_obj,
        'stats': stats,
        'downloading_count': stats['downloading'],
        'page_title': '다운로드 관리',
    }
    
    return render(request, 'dashboard/downloads.html', context)


@login_required
def settings_page(request):
    """설정 페이지"""
    # 현재 설정 불러오기
    settings_data = {
        'retention_days': Settings.get_setting('retention_days', 14),
        'check_interval': Settings.get_setting('check_interval_minutes', 1),
        'default_quality': Settings.get_setting('default_quality', 'both'),
        'telegram_bot_token': Settings.get_setting('telegram_bot_token', ''),
        'telegram_chat_id': Settings.get_setting('telegram_chat_id', ''),
        'notify_live_start': Settings.get_setting('notify_live_start', True),
        'notify_download_complete': Settings.get_setting('notify_download_complete', True),
        'notify_errors': Settings.get_setting('notify_errors', True),
        'download_path': Settings.get_setting('download_path', '/downloads'),
    }
    
    # 토큰 마스킹
    if settings_data['telegram_bot_token']:
        token = settings_data['telegram_bot_token']
        if len(token) > 20:
            settings_data['telegram_token_masked'] = token[:10] + '*' * (len(token) - 20) + token[-10:]
        else:
            settings_data['telegram_token_masked'] = '*' * len(token)
    
    # 디스크 사용량
    download_path = settings_data['download_path']
    try:
        usage = shutil.disk_usage(download_path)
        disk_usage = {
            'total': format_file_size(usage.total),
            'used': format_file_size(usage.used),
            'free': format_file_size(usage.free),
            'percent': round((usage.used / usage.total) * 100, 1)
        }
    except:
        disk_usage = {
            'total': 'N/A',
            'used': 'N/A',
            'free': 'N/A',
            'percent': 0
        }
    
    # 버전 정보
    context = {
        'settings': settings_data,
        'disk_usage': disk_usage,
        'version': '1.0.0',
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'django_version': django.get_version(),
        'ytdlp_version': yt_dlp.version.__version__,
        'page_title': '설정',
    }
    
    return render(request, 'dashboard/settings.html', context)


@login_required
def logs_page(request):
    """시스템 로그 페이지"""
    logs = SystemLog.objects.all().order_by('-created_at')
    
    # 페이지네이션
    paginator = Paginator(logs, 100)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'logs': page_obj.object_list,
        'page_obj': page_obj,
        'page_title': '시스템 로그',
    }
    
    return render(request, 'dashboard/logs.html', context)


@login_required
def dashboard_activities_ajax(request):
    """대시보드 실시간 활동 데이터 조회"""
    try:
        # downloads 모듈 동적 임포트
        global Download
        if Download is None:
            from downloads.models import Download
        
        # 최근 24시간 활동
        since = timezone.now() - timedelta(hours=24)
        
        # 최근 라이브 스트림
        recent_streams = LiveStream.objects.filter(
            started_at__gte=since
        ).select_related('channel').order_by('-started_at')[:20]
        
        # 최근 다운로드
        recent_downloads = Download.objects.filter(
            created_at__gte=since
        ).select_related('live_stream__channel').order_by('-created_at')[:10]
        
        activities = []
        
        # 라이브 스트림 활동 추가
        for stream in recent_streams:
            activity_type = 'live_detected' if stream.status == 'live' else 'stream_ended'
            icon = 'play-circle' if stream.status == 'live' else 'check-circle'
            
            activities.append({
                'id': f'stream_{stream.id}',
                'type': activity_type,
                'message': f'새로운 라이브 스트림 감지' if stream.status == 'live' else '라이브 스트림 종료',
                'title': stream.title,
                'channel_name': stream.channel.name,
                'status': stream.status,
                'icon': icon,
                'timestamp': stream.started_at.isoformat(),
                'url': stream.url
            })
        
        # 다운로드 활동 추가
        for download in recent_downloads:
            if download.live_stream and download.live_stream.channel:
                status_map = {
                    'pending': 'pending',
                    'downloading': 'downloading', 
                    'completed': 'completed',
                    'failed': 'failed'
                }
                
                icon_map = {
                    'pending': 'clock',
                    'downloading': 'download',
                    'completed': 'check-circle',
                    'failed': 'x-circle'
                }
                
                message_map = {
                    'pending': '다운로드 대기 중',
                    'downloading': '다운로드 진행 중',
                    'completed': '다운로드 완료',
                    'failed': '다운로드 실패'
                }
                
                activities.append({
                    'id': f'download_{download.id}',
                    'type': 'download_status',
                    'message': message_map.get(download.status, '다운로드 상태 변경'),
                    'title': download.live_stream.title,
                    'channel_name': download.live_stream.channel.name,
                    'status': status_map.get(download.status, 'unknown'),
                    'icon': icon_map.get(download.status, 'clock'),
                    'timestamp': download.updated_at.isoformat(),
                    'quality': download.quality,
                    'file_size': format_file_size(download.file_size) if download.file_size else None
                })
        
        # 시간순 정렬
        activities.sort(key=lambda x: x['timestamp'], reverse=True)
        activities = activities[:15]  # 최근 15개만
        
        return JsonResponse({
            'success': True,
            'activities': activities
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'활동 데이터를 불러올 수 없습니다: {str(e)}'
        }, status=500)


@login_required 
def dashboard_stats_ajax(request):
    """대시보드 실시간 통계 데이터 조회"""
    try:
        # downloads 모듈 동적 임포트
        global Download
        if Download is None:
            from downloads.models import Download
        
        # 기본 통계
        stats = {
            'total_channels': Channel.objects.count(),
            'active_channels': Channel.objects.filter(is_active=True).count(),
            'total_live_streams': LiveStream.objects.count(),
            'current_live_count': LiveStream.objects.filter(status='live').count(),
        }
        
        # 다운로드 통계
        download_stats = Download.objects.aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
            pending=Count('id', filter=Q(status='pending')),
            downloading=Count('id', filter=Q(status='downloading')),
            failed=Count('id', filter=Q(status='failed')),
            total_size=Sum('file_size')
        )
        
        stats.update(download_stats)
        stats['total_storage_used'] = format_file_size(download_stats['total_size'] or 0)
        
        # 현재 라이브 스트림 목록
        current_live_streams = LiveStream.objects.filter(
            status='live'
        ).select_related('channel').values(
            'id', 'title', 'url', 'channel__name', 'started_at'
        )[:5]
        
        stats['live_streams'] = list(current_live_streams)
        
        return JsonResponse({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'message': f'통계 데이터를 불러올 수 없습니다: {str(e)}'
        }, status=500)


@login_required
def dashboard_live_streams_ajax(request):
    """현재 라이브 중인 스트림 목록 조회"""
    try:
        # downloads 모듈 동적 임포트
        global Download
        if Download is None:
            from downloads.models import Download
        
        live_streams = LiveStream.objects.filter(
            status='live'
        ).select_related('channel').order_by('-started_at')
        
        streams_data = []
        for stream in live_streams:
            # 해당 스트림의 다운로드 상태 확인
            download = Download.objects.filter(
                live_stream=stream
            ).order_by('-created_at').first()
            
            streams_data.append({
                'id': stream.id,
                'title': stream.title,
                'url': stream.url,
                'thumbnail': stream.thumbnail or '',
                'channel_name': stream.channel.name,
                'channel_id': stream.channel.channel_id,
                'started_at': stream.started_at.isoformat(),
                'download_status': download.status if download else None,
                'download_id': download.id if download else None
            })
        
        return JsonResponse({
            'success': True,
            'live_streams': streams_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'라이브 스트림 데이터를 불러올 수 없습니다: {str(e)}'
        }, status=500)


@login_required
def start_download_ajax(request, stream_id):
    """수동으로 다운로드 시작"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'}, status=405)
    
    try:
        # downloads 모듈 동적 임포트
        global Download
        if Download is None:
            from downloads.models import Download
        
        stream = LiveStream.objects.get(id=stream_id)
        
        # 이미 다운로드가 있는지 확인
        existing_download = Download.objects.filter(live_stream=stream).first()
        
        if existing_download:
            if existing_download.status in ['pending', 'downloading']:
                return JsonResponse({
                    'success': False,
                    'message': '이미 다운로드가 진행 중입니다.'
                })
            elif existing_download.status == 'completed':
                return JsonResponse({
                    'success': False,
                    'message': '이미 다운로드가 완료되었습니다.'
                })
        
        # 새 다운로드 생성
        from core.tasks import download_video
        
        # 고화질과 저화질 다운로드 모두 시작
        download_high = Download.objects.create(
            live_stream=stream,
            quality='high',
            status='pending'
        )
        
        download_low = Download.objects.create(
            live_stream=stream,
            quality='low', 
            status='pending'
        )
        
        # Celery 태스크 실행
        download_video.delay(download_high.id)
        download_video.delay(download_low.id)
        
        return JsonResponse({
            'success': True,
            'message': f'"{stream.title}" 다운로드를 시작했습니다.'
        })
        
    except LiveStream.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': '스트림을 찾을 수 없습니다.'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'다운로드 시작 중 오류가 발생했습니다: {str(e)}'
        }, status=500)
