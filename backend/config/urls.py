from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/account/", include("accounts.urls")),
    path("api/recruitment/", include("recruitment.urls")),
    path("api/", include("attendance.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if (settings.BASE_DIR / "frontend_dist" / "index.html").exists():
    urlpatterns += [path("<path:path>", TemplateView.as_view(template_name="index.html"))]
    urlpatterns += [path("", TemplateView.as_view(template_name="index.html"))]
