"""URL configuration for polymarket_project project."""

from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse
from pathlib import Path


def serve_frontend(request):
    """Serve the frontend index.html"""
    frontend_path = settings.BASE_DIR / 'frontend' / 'index.html'
    return FileResponse(open(frontend_path, 'rb'), content_type='text/html')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('wallet_analysis.urls')),
    # Serve the modern frontend at root
    path('', serve_frontend, name='frontend'),
    # Keep old dashboard at /old/
    path('old/', TemplateView.as_view(template_name='dashboard.html'), name='dashboard-old'),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static('/css/', document_root=settings.BASE_DIR / 'frontend' / 'css')
    urlpatterns += static('/js/', document_root=settings.BASE_DIR / 'frontend' / 'js')
