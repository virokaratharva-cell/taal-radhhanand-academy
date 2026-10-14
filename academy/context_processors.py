from django.utils import timezone
from .models import AcademySettings, AcademyAlert


def academy_context(request):
    """Provides academy settings and alert badges to all templates."""
    try:
        settings_obj = AcademySettings.get_settings()
        alert_count = AcademyAlert.objects.filter(is_dismissed=False).count() if request.user.is_authenticated else 0
    except Exception:
        settings_obj = None
        alert_count = 0

    return {
        'academy_settings': settings_obj,
        'unread_alerts_count': alert_count,
        'current_year': timezone.now().year,
    }
