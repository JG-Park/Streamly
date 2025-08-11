"""
YouTube 영상 추출 및 다운로드 API 뷰
"""

import os
import yt_dlp
from datetime import datetime, timedelta
from django.utils import timezone
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics

from downloads.models_manual import ManualDownload
from core.models import SystemLog
from .serializers_video import (
    VideoExtractSerializer,
    VideoDownloadSerializer,
    ManualDownloadSerializer,
    ManualDownloadDetailSerializer
)

import logging
logger = logging.getLogger('streamly')


class VideoExtractView(APIView):
    """YouTube 영상 정보 추출 API"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """URL로부터 영상 정보 추출"""
        serializer = VideoExtractSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        url = serializer.validated_data['url']
        
        # yt-dlp로 영상 정보 추출
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # 사용 가능한 포맷 정보 수집
                formats = []
                if 'formats' in info:
                    for f in info['formats']:
                        if f.get('vcodec') != 'none' or f.get('acodec') != 'none':
                            format_info = {
                                'format_id': f.get('format_id'),
                                'ext': f.get('ext'),
                                'resolution': f.get('resolution') or f'{f.get("width", "?")}x{f.get("height", "?")}',
                                'fps': f.get('fps'),
                                'vcodec': f.get('vcodec'),
                                'acodec': f.get('acodec'),
                                'filesize': f.get('filesize') or f.get('filesize_approx'),
                                'quality': f.get('quality'),
                                'format_note': f.get('format_note'),
                            }
                            
                            # 파일 크기 표시
                            if format_info['filesize']:
                                size_mb = format_info['filesize'] / (1024 * 1024)
                                format_info['filesize_display'] = f'{size_mb:.1f} MB'
                            else:
                                format_info['filesize_display'] = 'Unknown'
                            
                            formats.append(format_info)
                
                # 추천 포맷 선택 (최고 화질)
                best_format = None
                if formats:
                    # 비디오가 있는 포맷 중 가장 높은 품질 선택
                    video_formats = [f for f in formats if f.get('vcodec') not in ['none', None]]
                    if video_formats:
                        best_format = max(video_formats, key=lambda x: x.get('quality', 0))
                
                response_data = {
                    'video_id': info.get('id'),
                    'title': info.get('title'),
                    'channel': info.get('channel') or info.get('uploader'),
                    'duration': info.get('duration'),
                    'duration_display': self._format_duration(info.get('duration')),
                    'thumbnail': info.get('thumbnail'),
                    'description': info.get('description'),
                    'upload_date': info.get('upload_date'),
                    'view_count': info.get('view_count'),
                    'like_count': info.get('like_count'),
                    'is_live': info.get('is_live', False),
                    'formats': formats[:20],  # 최대 20개 포맷만 반환
                    'best_format': best_format,
                    'direct_url': None,  # CDN URL은 선택한 포맷에서 추출
                }
                
                # 라이브 스트림인 경우 경고 추가
                if info.get('is_live'):
                    response_data['warning'] = '현재 라이브 스트리밍 중입니다. 종료 후 다운로드 가능합니다.'
                
                SystemLog.log('INFO', 'video_extract', 
                             f"영상 정보 추출: {info.get('title')}",
                             {'video_id': info.get('id'), 'url': url})
                
                return Response(response_data)
                
        except Exception as e:
            logger.error(f"영상 정보 추출 실패: {str(e)}")
            SystemLog.log('ERROR', 'video_extract', 
                         f"영상 정보 추출 실패: {str(e)}",
                         {'url': url})
            return Response(
                {'error': f'영상 정보 추출 실패: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def _format_duration(self, seconds):
        """초를 시:분:초 형식으로 변환"""
        if not seconds:
            return "00:00"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"


class VideoDownloadView(APIView):
    """YouTube 영상 다운로드 API"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """영상 다운로드 시작"""
        serializer = VideoDownloadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        
        # 중복 다운로드 확인
        existing = ManualDownload.objects.filter(
            video_id=data['video_id'],
            status__in=['pending', 'extracting', 'downloading']
        ).first()
        
        if existing:
            return Response(
                {'error': '이미 다운로드가 진행 중입니다.', 'download_id': existing.id},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ManualDownload 레코드 생성
        download = ManualDownload.objects.create(
            url=data['url'],
            video_id=data['video_id'],
            title=data['title'],
            channel_name=data.get('channel'),
            duration=data.get('duration'),
            thumbnail_url=data.get('thumbnail'),
            download_type=data['download_type'],
            quality=data.get('quality', 'best'),
            resolution=data.get('resolution'),
            video_codec=data.get('video_codec'),
            audio_codec=data.get('audio_codec'),
            requested_by=request.user,
            status='pending'
        )
        
        # 다운로드 타입에 따라 처리
        if data['download_type'] == 'direct':
            # CDN 다이렉트 URL 추출
            try:
                format_id = data.get('format_id')
                direct_url = self._extract_direct_url(data['url'], format_id)
                
                if direct_url:
                    download.direct_url = direct_url
                    download.direct_url_expires = timezone.now() + timedelta(hours=6)
                    download.status = 'completed'
                    download.completed_at = timezone.now()
                    download.save()
                    
                    SystemLog.log('INFO', 'video_download', 
                                 f"CDN URL 추출 완료: {data['title']}",
                                 {'video_id': data['video_id'], 'type': 'direct'})
                    
                    return Response({
                        'download_id': download.id,
                        'direct_url': direct_url,
                        'expires_at': download.direct_url_expires,
                        'message': 'CDN URL이 성공적으로 추출되었습니다.'
                    })
                else:
                    download.fail_download('CDN URL 추출 실패')
                    return Response(
                        {'error': 'CDN URL 추출에 실패했습니다.'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            except Exception as e:
                download.fail_download(str(e))
                return Response(
                    {'error': f'URL 추출 중 오류: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        else:  # server
            # 서버 다운로드는 Celery 태스크로 처리
            from core.tasks import download_manual_video
            task_result = download_manual_video.delay(download.id)
            
            SystemLog.log('INFO', 'video_download', 
                         f"서버 다운로드 시작: {data['title']}",
                         {'video_id': data['video_id'], 'type': 'server', 'task_id': str(task_result.id)})
            
            return Response({
                'download_id': download.id,
                'task_id': str(task_result.id),
                'message': '다운로드가 시작되었습니다.'
            }, status=status.HTTP_201_CREATED)
    
    def _extract_direct_url(self, video_url, format_id=None):
        """CDN 다이렉트 URL 추출"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        
        if format_id:
            ydl_opts['format'] = format_id
        else:
            ydl_opts['format'] = 'best'
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                # 직접 URL 추출
                if 'url' in info:
                    return info['url']
                
                # 포맷에서 URL 찾기
                if 'formats' in info and format_id:
                    for f in info['formats']:
                        if f.get('format_id') == format_id:
                            return f.get('url')
                
                # 최고 품질 포맷의 URL 반환
                if 'formats' in info:
                    best = max(info['formats'], key=lambda x: x.get('quality', 0))
                    return best.get('url')
                
                return None
        except Exception as e:
            logger.error(f"Direct URL 추출 실패: {str(e)}")
            return None


class ManualDownloadListView(generics.ListAPIView):
    """수동 다운로드 목록 조회"""
    serializer_class = ManualDownloadSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        queryset = ManualDownload.objects.all()
        
        # 필터링
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        download_type = self.request.query_params.get('type')
        if download_type:
            queryset = queryset.filter(download_type=download_type)
        
        # 사용자 필터 (관리자가 아닌 경우 본인 것만)
        if not self.request.user.is_staff:
            queryset = queryset.filter(requested_by=self.request.user)
        
        return queryset.order_by('-created_at')


class ManualDownloadDetailView(generics.RetrieveUpdateDestroyAPIView):
    """수동 다운로드 상세 조회/수정/삭제"""
    serializer_class = ManualDownloadDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        queryset = ManualDownload.objects.all()
        
        # 사용자 필터 (관리자가 아닌 경우 본인 것만)
        if not self.request.user.is_staff:
            queryset = queryset.filter(requested_by=self.request.user)
        
        return queryset
    
    def destroy(self, request, *args, **kwargs):
        """다운로드 삭제 (파일도 함께 삭제)"""
        instance = self.get_object()
        
        # 파일 삭제
        if instance.file_path and os.path.exists(instance.file_path):
            try:
                os.remove(instance.file_path)
                SystemLog.log('INFO', 'manual_download', 
                             f"다운로드 파일 삭제: {instance.title}",
                             {'download_id': instance.id, 'file_path': instance.file_path})
            except Exception as e:
                logger.error(f"파일 삭제 실패: {str(e)}")
        
        # DB 레코드 삭제
        instance.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)