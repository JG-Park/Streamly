"""
Streamly 유틸리티 함수들
"""

import os
import re
import logging
import yt_dlp
from urllib.parse import urlparse, parse_qs
from django.conf import settings
from typing import Optional, Dict, Any

logger = logging.getLogger('streamly')

# YouTube API 서비스 import (선택적)
try:
    from .youtube_api import youtube_api_service
    from .api_backup_service import api_backup_service
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False
    logger.warning("YouTube API 서비스를 사용할 수 없습니다.")


class YouTubeLiveChecker:
    """YouTube 라이브 스트림 확인 유틸리티"""
    
    def __init__(self):
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'get_info': True,
            'socket_timeout': 10,  # 소켓 타임아웃 10초
        }
    
    def extract_channel_id(self, url: str) -> Optional[str]:
        """URL에서 채널 ID 추출"""
        try:
            parsed = urlparse(url)
            
            # 채널 URL 패턴들
            if '/channel/' in url:
                return url.split('/channel/')[1].split('/')[0].split('?')[0]
            elif '/@' in url:
                # Handle 핸들 형태 (@username)의 경우 yt-dlp로 채널 정보 가져오기
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    return info.get('channel_id')
            elif '/c/' in url:
                # Custom URL의 경우
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    return info.get('channel_id')
            elif '/user/' in url:
                # Legacy user URL
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    return info.get('channel_id')
            
        except Exception as e:
            logger.error(f"채널 ID 추출 실패: {url}, 에러: {e}")
            
        return None
    
    def get_channel_info(self, channel_url: str) -> Optional[Dict[str, Any]]:
        """채널 정보 가져오기 (yt-dlp 우선 사용)"""
        # yt-dlp를 먼저 시도 (API 할당량 절약)
        result = self._get_channel_info_ydlp(channel_url)
        
        # yt-dlp가 실패하고 API가 사용 가능한 경우에만 API 시도
        if not result and YOUTUBE_API_AVAILABLE and youtube_api_service.is_available():
            try:
                result = youtube_api_service.get_channel_info_by_url(channel_url)
            except Exception as e:
                logger.warning(f"YouTube API 사용 실패, yt-dlp로 폴백: {e}")
        
        return result
    
    def _get_channel_info_ydlp(self, channel_url: str) -> Optional[Dict[str, Any]]:
        """yt-dlp로 채널 정보 가져오기 (타임아웃 설정)"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        
        def fetch_channel_info():
            try:
                # 채널 정보만 가져오기 위한 최적화 옵션
                quick_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': True,  # 플레이리스트 정보만 가져오기
                    'skip_download': True,
                    'socket_timeout': 10,
                    'http_chunk_size': 10485760,  # 10MB 청크
                }
                
                with yt_dlp.YoutubeDL(quick_opts) as ydl:
                    # 채널 URL 직접 사용 (@ 핸들도 지원)
                    info = ydl.extract_info(channel_url, download=False)
                    
                    # 채널 정보 추출
                    channel_id = info.get('channel_id') or info.get('uploader_id')
                    channel_name = info.get('channel') or info.get('uploader') or info.get('title')
                    
                    if channel_id:
                        return {
                            'channel_id': channel_id,
                            'channel_name': channel_name,
                            'channel_url': f"https://www.youtube.com/channel/{channel_id}",
                        }
            except Exception as e:
                logger.error(f"yt-dlp로 채널 정보 가져오기 실패: {channel_url}, 에러: {e}")
                return None
        
        # ThreadPoolExecutor를 사용하여 타임아웃 처리
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fetch_channel_info)
            try:
                return future.result(timeout=15)  # 15초 타임아웃
            except TimeoutError:
                logger.error(f"yt-dlp 타임아웃: {channel_url}")
                return None
    
    def check_live_streams(self, channel_id: str) -> list:
        """채널의 라이브 스트림 확인 (yt-dlp 우선, API는 백업)"""
        # yt-dlp를 기본으로 사용
        try:
            logger.info(f"yt-dlp로 라이브 스트림 확인 중: {channel_id}")
            result = self._check_live_streams_ydlp(channel_id)
            if result:
                return result
        except Exception as e:
            logger.warning(f"yt-dlp 실패, API로 폴백: {e}")
        
        # yt-dlp 실패 시 API 사용 (백업)
        if YOUTUBE_API_AVAILABLE and youtube_api_service.is_available():
            try:
                logger.info(f"YouTube API로 라이브 스트림 확인 중: {channel_id}")
                return youtube_api_service.get_live_streams(channel_id)
            except Exception as e:
                logger.error(f"YouTube API도 실패: {e}")
        
        return []
    
    def _check_live_streams_ydlp(self, channel_id: str) -> list:
        """yt-dlp로 라이브 스트림 확인 (개선된 방법)"""
        live_streams = []
        
        # 방법 1: /streams URL로 최근 스트림 확인
        try:
            channel_url = f"https://www.youtube.com/channel/{channel_id}/streams"
            logger.info(f"라이브 스트림 확인: {channel_url}")
            
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,  # 플레이리스트 정보만
                'skip_download': True,
                'playlistend': 10,  # 최근 10개 확인
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                
                if info and 'entries' in info:
                    # 최근 10개 비디오 중 라이브 확인
                    for entry in info.get('entries', [])[:10]:
                        if entry and entry.get('id'):
                            # 각 비디오의 상세 정보 확인
                            video_url = f"https://www.youtube.com/watch?v={entry.get('id')}"
                            try:
                                video_opts = {
                                    'quiet': True,
                                    'no_warnings': True,
                                    'skip_download': True,
                                }
                                with yt_dlp.YoutubeDL(video_opts) as video_ydl:
                                    video_info = video_ydl.extract_info(video_url, download=False)
                                    
                                    if video_info and video_info.get('is_live'):
                                        live_streams.append({
                                            'video_id': video_info.get('id'),
                                            'title': video_info.get('title', ''),
                                            'url': video_info.get('webpage_url', ''),
                                            'thumbnail': video_info.get('thumbnail', ''),
                                            'is_live': True,
                                            'started_at': video_info.get('timestamp'),
                                        })
                                        logger.info(f"라이브 발견: {video_info.get('title')}")
                            except Exception as ve:
                                logger.debug(f"비디오 확인 실패 {video_url}: {ve}")
                                continue
                                
        except Exception as e:
            logger.warning(f"/streams URL 실패, /live 시도: {e}")
            
            # 방법 2: /live URL 사용 (폴백)
            try:
                channel_url = f"https://www.youtube.com/channel/{channel_id}/live"
                
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    try:
                        info = ydl.extract_info(channel_url, download=False)
                        
                        if info and info.get('is_live'):
                            live_streams.append({
                                'video_id': info.get('id'),
                                'title': info.get('title', ''),
                                'url': info.get('webpage_url', ''),
                                'thumbnail': info.get('thumbnail', ''),
                                'is_live': True,
                                'started_at': info.get('timestamp'),
                            })
                            logger.info(f"라이브 발견 (/live): {info.get('title')}")
                            
                    except yt_dlp.utils.ExtractorError as e:
                        if 'not currently live' in str(e) or 'is not live' in str(e):
                            logger.info(f"채널 {channel_id}: 현재 라이브 없음")
                        else:
                            logger.warning(f"/live 에러: {e}")
                            
            except Exception as e2:
                logger.error(f"라이브 확인 실패: {e2}")
        
        logger.info(f"채널 {channel_id}: {len(live_streams)}개 라이브 발견")
        return live_streams
    
    def get_video_info(self, video_url: str) -> Optional[Dict[str, Any]]:
        """비디오 정보 가져오기 (스마트 백업 시스템 사용)"""
        # URL에서 비디오 ID 추출
        video_id = None
        if 'v=' in video_url:
            video_id = video_url.split('v=')[1].split('&')[0]
        elif 'youtu.be/' in video_url:
            video_id = video_url.split('youtu.be/')[1].split('?')[0]
        
        if not YOUTUBE_API_AVAILABLE or not youtube_api_service.is_available() or not video_id:
            # API 사용 불가 시 직접 yt-dlp 사용
            return self._get_video_info_ydlp(video_url)
        
        # 스마트 백업 시스템으로 실행
        return api_backup_service.execute_with_backup(
            lambda vid: youtube_api_service.get_video_details(vid),
            lambda url: self._get_video_info_ydlp(url),
            "get_video_info",
            video_id if video_id else video_url
        )
    
    def _get_video_info_ydlp(self, video_url: str) -> Optional[Dict[str, Any]]:
        """yt-dlp로 비디오 정보 가져오기"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                return {
                    'video_id': info.get('id'),
                    'title': info.get('title'),
                    'url': info.get('webpage_url'),
                    'thumbnail': info.get('thumbnail'),
                    'channel_id': info.get('channel_id'),
                    'channel_name': info.get('uploader') or info.get('channel'),
                    'is_live': info.get('is_live', False),
                    'was_live': info.get('was_live', False),
                    'duration': info.get('duration'),
                    'upload_date': info.get('upload_date'),
                }
                
        except Exception as e:
            logger.error(f"yt-dlp로 비디오 정보 가져오기 실패: {video_url}, 에러: {e}")
            
        return None


def create_download_path(channel_name: str, quality: str) -> str:
    """다운로드 경로 생성"""
    # 파일명에 사용할 수 없는 문자 제거
    safe_channel_name = re.sub(r'[<>:"/\\|?*]', '_', channel_name)
    
    base_path = settings.DOWNLOAD_PATH
    download_path = os.path.join(base_path, quality, safe_channel_name)
    
    # 디렉토리 생성
    os.makedirs(download_path, exist_ok=True)
    
    return download_path


def get_file_size(file_path: str) -> Optional[int]:
    """파일 크기 가져오기 (바이트)"""
    try:
        if os.path.exists(file_path):
            return os.path.getsize(file_path)
    except OSError:
        pass
    return None


def format_file_size(size_bytes: int) -> str:
    """파일 크기를 읽기 쉬운 형태로 변환"""
    if size_bytes == 0:
        return "0B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"


def sanitize_filename(filename: str) -> str:
    """파일명 안전하게 만들기"""
    # 파일명에 사용할 수 없는 문자들 제거
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # 길이 제한 (Windows 파일명 길이 제한 고려)
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    
    return sanitized.strip()


# 호환성을 위한 별칭 클래스
class YouTubeExtractor(YouTubeLiveChecker):
    """
    YouTubeLiveChecker의 별칭 클래스 (호환성 유지)
    채널 정보 추출을 위한 메서드들을 제공합니다.
    """
    pass