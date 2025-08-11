"""
Streamly URL 설정
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView

urlpatterns = [
    # 루트 경로를 대시보드로 리다이렉트
    path('', RedirectView.as_view(url='/dashboard/', permanent=False)),
    
    # 인증 관련
    path('login/', auth_views.LoginView.as_view(template_name='auth/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='/login/'), name='logout'),
    
    # 통합 대시보드
    path('dashboard/', include('core.urls')),
    
    # API v1
    path('api/v1/', include('api.urls')),
    
    # Django Admin (개발용)
    path('admin/', admin.site.urls) if settings.DEBUG else path('admin/', RedirectView.as_view(url='/dashboard/', permanent=False)),
]

# 개발 환경에서 미디어 파일 서빙
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)