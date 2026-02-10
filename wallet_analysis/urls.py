"""URL configuration for wallet_analysis API."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'wallets', views.WalletViewSet)
router.register(r'markets', views.MarketViewSet)
router.register(r'trades', views.TradeViewSet)
router.register(r'activities', views.ActivityViewSet)
router.register(r'analyses', views.AnalysisRunViewSet)

urlpatterns = [
    # Wallet management - MUST be before router to avoid conflicts
    path('wallets/add/', views.add_wallet, name='wallet-add'),
    path('wallets/<int:pk>/refresh/', views.refresh_wallet, name='wallet-refresh'),
    path('wallets/<int:pk>/delete/', views.delete_wallet, name='wallet-delete'),
    path('wallets/<int:pk>/update/', views.update_wallet, name='wallet-update'),
    path('wallets/<int:pk>/extend-range/', views.extend_wallet_range, name='wallet-extend-range'),
    # Task status
    path('tasks/<str:task_id>/', views.task_status, name='task-status'),
    # Other endpoints
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('analyze/', views.analyze_wallet, name='analyze'),
    # Router URLs (ViewSets)
    path('', include(router.urls)),
]
