from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.sites.urls")),
    path("api/", include("apps.monitoring.urls")),
    path("api/", include("apps.orders.urls")),
    path("api/", include("apps.catalog.urls")),
    path("api/", include("apps.sync.urls")),
    path("api/", include("apps.mailer.urls")),
]

# Serve user-uploaded media (site-note attachments) from the dev server.
# In production a real web server / object store fronts MEDIA_URL instead.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
