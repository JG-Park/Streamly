"""
대시보드 URL 설정
"""
from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    # 메인 대시보드
    path('', views.dashboard_index, name='index'),
    
    # 채널 관리
    path('channels/', views.channels_page, name='channels'),
    
    # 라이브 스트림
    path('streams/', views.streams_page, name='streams'),
    
    # 다운로드 관리
    path('downloads/', views.downloads_page, name='downloads'),
    
    # YouTube 수동 다운로드
    path('youtube-download/', views.manual_download_page, name='manual_download'),
    
    # 설정
    path('settings/', views.settings_page, name='settings'),
    
    # 시스템 로그
    path('logs/', views.logs_page, name='logs'),
]