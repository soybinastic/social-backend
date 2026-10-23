from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core.views import HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.posts.urls")),
    path("api/", include("apps.comments.urls")),
    path("api/", include("apps.notifications.urls")),
    path("api/", include("apps.chat.urls")),
]

if settings.DEBUG:
    # Serve locally stored uploads so LocalFileSystemStorage URLs resolve.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
