"""
채널 관리 뷰들
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt, csrf_protect
import json
import logging

from .models import Channel, LiveStream
from .forms import ChannelAddForm, ChannelEditForm, ChannelBulkActionForm
from core.utils import YouTubeExtractor
from core.tasks import check_channel_live_streams

logger = logging.getLogger('streamly')


@staff_member_required
@require_http_methods(["POST"])
def add_channel_ajax(request):
    """Ajax를 통한 채널 추가"""
    try:
        data = json.loads(request.body)
        
        # youtube_url이 없으면 channel_url도 확인
        if 'channel_url' in data and 'youtube_url' not in data:
            data['youtube_url'] = data['channel_url']
        
        # is_active 기본값 설정
        if 'is_active' not in data:
            data['is_active'] = True
            
        form = ChannelAddForm(data)
        
        if form.is_valid():
            channel = form.save()
            
            # 즉시 라이브 스트림 확인 시작
            try:
                check_channel_live_streams.delay(channel.id)
            except Exception as task_error:
                logger.error(f"Celery 태스크 실행 실패: {task_error}")
            
            return JsonResponse({
                'success': True,
                'message': f'채널 "{channel.name}"이 성공적으로 추가되었습니다.',
                'channel': {
                    'id': channel.id,
                    'name': channel.name,
                    'channel_id': channel.channel_id,
                    'url': channel.url,
                    'is_active': channel.is_active,
                    'created_at': channel.created_at.isoformat(),
                }
            })
        else:
            logger.error(f"폼 검증 실패: {form.errors}")
            return JsonResponse({
                'success': False,
                'errors': form.errors,
                'message': '채널 추가 실패: ' + str(form.errors)
            }, status=400)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '잘못된 데이터 형식입니다.'
        }, status=400)
    except Exception as e:
        logger.error(f"채널 추가 중 오류: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'채널 추가 중 오류가 발생했습니다: {str(e)}'
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
def edit_channel_ajax(request, channel_id):
    """Ajax를 통한 채널 편집"""
    try:
        channel = get_object_or_404(Channel, id=channel_id)
        data = json.loads(request.body)
        form = ChannelEditForm(data, instance=channel)
        
        if form.is_valid():
            channel = form.save()
            
            return JsonResponse({
                'success': True,
                'message': f'채널 "{channel.name}"이 성공적으로 수정되었습니다.',
                'channel': {
                    'id': channel.id,
                    'name': channel.name,
                    'is_active': channel.is_active,
                    'updated_at': channel.updated_at.isoformat(),
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': form.errors
            }, status=400)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '잘못된 데이터 형식입니다.'
        }, status=400)
    except Exception as e:
        logger.error(f"채널 수정 중 오류: {e}")
        return JsonResponse({
            'success': False,
            'message': '채널 수정 중 오류가 발생했습니다.'
        }, status=500)


@staff_member_required
@require_http_methods(["DELETE"])
def delete_channel_ajax(request, channel_id):
    """Ajax를 통한 채널 삭제"""
    try:
        channel = get_object_or_404(Channel, id=channel_id)
        channel_name = channel.name
        
        # 관련 데이터 정보 수집
        live_streams_count = LiveStream.objects.filter(channel=channel).count()
        
        channel.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'채널 "{channel_name}"과 관련된 {live_streams_count}개의 라이브 스트림 기록이 삭제되었습니다.'
        })
        
    except Exception as e:
        logger.error(f"채널 삭제 중 오류: {e}")
        return JsonResponse({
            'success': False,
            'message': '채널 삭제 중 오류가 발생했습니다.'
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
def toggle_channel_ajax(request, channel_id):
    """Ajax를 통한 채널 활성화/비활성화 토글"""
    try:
        channel = get_object_or_404(Channel, id=channel_id)
        channel.is_active = not channel.is_active
        channel.save(update_fields=['is_active'])
        
        status_text = "활성화" if channel.is_active else "비활성화"
        
        return JsonResponse({
            'success': True,
            'message': f'채널 "{channel.name}"이 {status_text}되었습니다.',
            'is_active': channel.is_active
        })
        
    except Exception as e:
        logger.error(f"채널 토글 중 오류: {e}")
        return JsonResponse({
            'success': False,
            'message': '채널 상태 변경 중 오류가 발생했습니다.'
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
def check_channel_now_ajax(request, channel_id):
    """Ajax를 통한 즉시 채널 확인"""
    try:
        channel = get_object_or_404(Channel, id=channel_id)
        
        # Celery 태스크로 즉시 확인 실행
        check_channel_live_streams.delay(channel.id)
        
        return JsonResponse({
            'success': True,
            'message': f'채널 "{channel.name}" 확인을 시작했습니다.'
        })
        
    except Exception as e:
        logger.error(f"채널 즉시 확인 중 오류: {e}")
        return JsonResponse({
            'success': False,
            'message': '채널 확인 중 오류가 발생했습니다.'
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
def preview_channel_ajax(request):
    """Ajax를 통한 채널 미리보기 (URL 검증)"""
    try:
        data = json.loads(request.body)
        youtube_url = data.get('youtube_url', '').strip()
        
        if not youtube_url:
            return JsonResponse({
                'success': False,
                'message': 'YouTube URL을 입력해주세요.'
            }, status=400)
        
        # YouTubeExtractor로 채널 정보 추출
        extractor = YouTubeExtractor()
        channel_info = extractor.get_channel_info(youtube_url)
        
        if not channel_info:
            return JsonResponse({
                'success': False,
                'message': '채널 정보를 가져올 수 없습니다. URL을 다시 확인해주세요.'
            }, status=400)
        
        # 중복 채널 확인
        is_duplicate = Channel.objects.filter(
            channel_id=channel_info['channel_id']
        ).exists()
        
        return JsonResponse({
            'success': True,
            'channel_info': {
                'channel_id': channel_info['channel_id'],
                'name': channel_info['channel_name'],
                'url': channel_info['channel_url'],
                'is_duplicate': is_duplicate
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '잘못된 데이터 형식입니다.'
        }, status=400)
    except Exception as e:
        logger.error(f"채널 미리보기 중 오류: {e}")
        return JsonResponse({
            'success': False,
            'message': '채널 정보를 가져오는 중 오류가 발생했습니다.'
        }, status=500)


@staff_member_required
def channels_list_ajax(request):
    """Ajax를 통한 채널 목록 조회 (페이지네이션 지원)"""
    try:
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 12))
        search = request.GET.get('search', '').strip()
        status_filter = request.GET.get('status', 'all')  # all, active, inactive
        
        # 기본 쿼리
        channels = Channel.objects.all()
        
        # 검색 필터
        if search:
            channels = channels.filter(
                Q(name__icontains=search) | 
                Q(channel_id__icontains=search)
            )
        
        # 상태 필터
        if status_filter == 'active':
            channels = channels.filter(is_active=True)
        elif status_filter == 'inactive':
            channels = channels.filter(is_active=False)
        
        # 정렬
        channels = channels.order_by('-is_active', 'name')
        
        # 페이지네이션
        paginator = Paginator(channels, per_page)
        page_obj = paginator.get_page(page)
        
        # 채널 데이터 구성
        channels_data = []
        for channel in page_obj:
            # 최근 라이브 스트림 정보
            recent_stream = LiveStream.objects.filter(
                channel=channel
            ).order_by('-started_at').first()
            
            channels_data.append({
                'id': channel.id,
                'name': channel.name,
                'channel_id': channel.channel_id,
                'url': channel.url,
                'is_active': channel.is_active,
                'last_checked': channel.last_checked.isoformat() if channel.last_checked else None,
                'created_at': channel.created_at.isoformat(),
                'recent_stream': {
                    'title': recent_stream.title if recent_stream else None,
                    'status': recent_stream.status if recent_stream else None,
                    'started_at': recent_stream.started_at.isoformat() if recent_stream else None
                } if recent_stream else None
            })
        
        return JsonResponse({
            'success': True,
            'channels': channels_data,
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'per_page': per_page
            }
        })
        
    except Exception as e:
        logger.error(f"채널 목록 조회 중 오류: {e}")
        return JsonResponse({
            'success': False,
            'message': '채널 목록을 가져오는 중 오류가 발생했습니다.'
        }, status=500)
