from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import mcp_views, views

urlpatterns = [
    path('health/', views.health, name='health'),
    path('signup/', views.SignupView.as_view(), name='signup'),
    path('signin/', views.SigninView.as_view(), name='signin'),
    path(
        'password-reset/',
        views.PasswordResetRequestView.as_view(),
        name='password-reset',
    ),
    path(
        'password-reset/confirm/',
        views.PasswordResetConfirmView.as_view(),
        name='password-reset-confirm',
    ),
    path('auth/google/', mcp_views.GoogleAuthView.as_view(), name='google-auth'),
    path('users/', mcp_views.UserListView.as_view(), name='user-list'),
    path(
        'users/me/change-password/',
        mcp_views.SelfChangePasswordView.as_view(),
        name='self-change-password',
    ),
    path(
        'users/<str:username>/change-password/',
        mcp_views.AdminChangePasswordView.as_view(),
        name='admin-change-password',
    ),
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
]
