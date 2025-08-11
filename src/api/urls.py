"""
API v1 URL 설정
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# API 라우터 설정
router = DefaultRouter()
router.register('channels', views.ChannelViewSet, basename='channel')
router.register('streams', views.LiveStreamViewSet, basename='stream')
router.register('downloads', views.DownloadViewSet, basename='download')
router.register('settings', views.SettingsViewSet, basename='setting')
router.register('logs', views.SystemLogViewSet, basename='log')

urlpatterns = [
    # 채널 미리보기 (라우터보다 먼저 정의)
    path('channel-preview/', views.ChannelPreviewView.as_view(), name='channel-preview'),
    
    # 대시보드 통계
    path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),
    
    # 시스템 관리
    path('system/management/', views.SystemManagementView.as_view(), name='system-management'),
    
    # 텔레그램
    path('telegram/test/', views.TelegramTestAPIView.as_view(), name='telegram-test'),
    
    # DRF 라우터 (마지막에 위치)
    path('', include(router.urls)),
]