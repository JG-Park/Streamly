from django.apps import AppConfig


class ChannelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "channels"
    
    def ready(self):
        import channels.signals  # 신호 등록
