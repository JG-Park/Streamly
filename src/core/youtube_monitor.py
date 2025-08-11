"""
YouTube 채널 모니터링을 위한 효율적인 시스템
API 할당량을 최소화하면서 실시간 모니터링 제공
"""

import re
import json
import logging
import requests
import yt_dlp
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger('streamly')


class EfficientYouTubeMonitor:
    """
    YouTube 모니터링 최적화 클래스
    - RSS 피드 우선 사용
    - yt-dlp 폴백
    - API는 최소한으로만 사용
    """
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # yt-dlp 옵션 (쿠키 파일 사용 가능)
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'force_generic_extractor': False,
            'cookiefile': 'cookies.txt',  # 봇 감지 회피용
        }
    
    def check_channel_rss(self, channel_id: str) -> List[Dict[str, Any]]:
        """
        RSS 피드로 최신 동영상 확인 (API 소비 없음)
        YouTube는 각 채널에 RSS 피드 제공
        """
        try:
            # YouTube RSS 피드 URL
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            
            response = self.session.get(rss_url, timeout=10)
            response.raise_for_status()
            
            # RSS XML 파싱 (간단한 정규식 사용)
            content = response.text
            
            videos = []
            # 비디오 ID 추출
            video_ids = re.findall(r'<yt:videoId>([^<]+)</yt:videoId>', content)
            titles = re.findall(r'<media:title>([^<]+)</media:title>', content)
            published = re.findall(r'<published>([^<]+)</published>', content)
            
            for i, video_id in enumerate(video_ids[:5]):  # 최근 5개만
                videos.append({
                    'video_id': video_id,
                    'title': titles[i] if i < len(titles) else '',
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'published': published[i] if i < len(published) else '',
                })
            
            return videos
            
        except Exception as e:
            logger.debug(f"RSS 피드 확인 실패 (채널 {channel_id}): {e}")
            return []
    
    def check_video_is_live(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        특정 비디오가 라이브 중인지 확인 (yt-dlp 사용)
        """
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info.get('is_live'):
                    return {
                        'video_id': video_id,
                        'title': info.get('title', ''),
                        'url': url,
                        'thumbnail': info.get('thumbnail', ''),
                        'is_live': True,
                        'viewer_count': info.get('view_count'),
                        'like_count': info.get('like_count'),
                        'description': info.get('description', '')[:500],
                    }
                    
        except Exception as e:
            logger.debug(f"비디오 라이브 확인 실패 ({video_id}): {e}")
            
        return None
    
    def check_channel_page(self, channel_id: str) -> List[Dict[str, Any]]:
        """
        채널 페이지를 직접 스크래핑하여 라이브 확인
        """
        try:
            # 채널의 라이브 탭 직접 접근
            live_url = f"https://www.youtube.com/channel/{channel_id}/live"
            
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(live_url, download=False)
                
                live_streams = []
                
                # 단일 라이브 스트림
                if info.get('is_live'):
                    live_streams.append({
                        'video_id': info.get('id'),
                        'title': info.get('title', ''),
                        'url': info.get('webpage_url', ''),
                        'thumbnail': info.get('thumbnail', ''),
                        'is_live': True,
                    })
                
                # 여러 라이브 스트림 (플레이리스트)
                elif 'entries' in info:
                    for entry in info.get('entries', [])[:3]:  # 최대 3개
                        if entry and entry.get('is_live'):
                            live_streams.append({
                                'video_id': entry.get('id'),
                                'title': entry.get('title', ''),
                                'url': f"https://www.youtube.com/watch?v={entry.get('id')}",
                                'thumbnail': entry.get('thumbnail', ''),
                                'is_live': True,
                            })
                
                return live_streams
                
        except Exception as e:
            logger.debug(f"채널 페이지 확인 실패 ({channel_id}): {e}")
            
        return []
    
    def smart_check_channel(self, channel_id: str, last_live_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        스마트 채널 체크 전략
        1. RSS로 최신 비디오 확인
        2. 최근 비디오 중 라이브 가능성 있는 것만 체크
        3. 실패 시 채널 페이지 직접 확인
        """
        result = {
            'channel_id': channel_id,
            'live_streams': [],
            'recent_videos': [],
            'check_method': None,
            'api_used': False
        }
        
        # 1단계: RSS 피드 확인 (API 소비 없음)
        recent_videos = self.check_channel_rss(channel_id)
        result['recent_videos'] = recent_videos
        
        if recent_videos:
            result['check_method'] = 'rss'
            
            # 최근 1시간 내 게시된 비디오만 라이브 체크
            for video in recent_videos[:2]:  # 최대 2개만 체크
                published_str = video.get('published', '')
                if published_str:
                    try:
                        # ISO 형식 날짜 파싱
                        published = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
                        if (datetime.now(published.tzinfo) - published).total_seconds() < 3600:
                            # 1시간 이내 비디오는 라이브 확인
                            live_info = self.check_video_is_live(video['video_id'])
                            if live_info:
                                result['live_streams'].append(live_info)
                    except:
                        pass
        
        # 2단계: RSS 실패 시 채널 페이지 직접 확인
        if not result['live_streams'] and not recent_videos:
            result['check_method'] = 'channel_page'
            live_streams = self.check_channel_page(channel_id)
            result['live_streams'] = live_streams
        
        return result
    
    def get_channel_check_interval(self, channel_id: str, history: List[datetime]) -> int:
        """
        채널별 체크 주기 동적 결정
        - 자주 라이브하는 채널: 1분
        - 가끔 라이브하는 채널: 5분
        - 거의 안하는 채널: 15분
        """
        if not history:
            return 5  # 기본 5분
        
        # 최근 7일간 라이브 횟수 계산
        now = datetime.now()
        recent_lives = [d for d in history if (now - d).days <= 7]
        
        if len(recent_lives) >= 7:  # 일주일에 7회 이상
            return 1
        elif len(recent_lives) >= 3:  # 일주일에 3회 이상
            return 5
        else:
            return 15


class HybridMonitorService:
    """
    하이브리드 모니터링 서비스
    - 채널 등록: YouTube API (1회)
    - 라이브 모니터링: RSS/yt-dlp (API 소비 없음)
    - 상세 정보: 필요시에만 API 호출
    """
    
    def __init__(self):
        self.monitor = EfficientYouTubeMonitor()
        self.use_api_for_details = True  # 상세 정보만 API 사용
    
    def register_channel(self, channel_url: str) -> Dict[str, Any]:
        """
        채널 등록 시에만 API 사용하여 정확한 정보 획득
        """
        from core.youtube_api import YouTubeAPIService
        
        # API로 채널 정보 획득 (1회)
        api_service = YouTubeAPIService()
        if api_service.is_available():
            channel_info = api_service.get_channel_info_by_url(channel_url)
            if channel_info:
                return channel_info
        
        # API 실패 시 yt-dlp 사용
        from core.utils import YouTubeLiveChecker
        checker = YouTubeLiveChecker()
        return checker.get_channel_info(channel_url)
    
    def check_channel_streams(self, channel_id: str) -> List[Dict[str, Any]]:
        """
        채널의 라이브 스트림 확인 (API 사용 없음)
        """
        result = self.monitor.smart_check_channel(channel_id)
        return result.get('live_streams', [])
    
    def get_stream_details(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        필요시에만 API로 상세 정보 획득
        """
        if self.use_api_for_details:
            from core.youtube_api import YouTubeAPIService
            api_service = YouTubeAPIService()
            
            if api_service.is_available():
                try:
                    # API로 상세 정보 획득
                    return api_service.get_video_details(video_id)
                except:
                    pass
        
        # API 실패 시 yt-dlp로 기본 정보
        return self.monitor.check_video_is_live(video_id)


# 전역 인스턴스
efficient_monitor = EfficientYouTubeMonitor()
hybrid_service = HybridMonitorService()