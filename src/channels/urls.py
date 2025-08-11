"""
채널 앱 URL 설정
"""

from django.urls import path
from . import views

app_name = 'channels'

urlpatterns = [
    # Ajax API endpoints
    path('ajax/add/', views.add_channel_ajax, name='add_ajax'),
    path('ajax/edit/<int:channel_id>/', views.edit_channel_ajax, name='edit_ajax'),
    path('ajax/delete/<int:channel_id>/', views.delete_channel_ajax, name='delete_ajax'),
    path('ajax/toggle/<int:channel_id>/', views.toggle_channel_ajax, name='toggle_ajax'),
    path('ajax/check/<int:channel_id>/', views.check_channel_now_ajax, name='check_now_ajax'),
    path('ajax/preview/', views.preview_channel_ajax, name='preview_ajax'),
    path('ajax/list/', views.channels_list_ajax, name='list_ajax'),
]