from django.urls import path

from . import auth_views, views

app_name = "core"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("auth/config/", auth_views.auth_config, name="auth-config"),
    path("auth/login/", auth_views.login, name="auth-login"),
    path("auth/register/", auth_views.register, name="auth-register"),
    path("auth/me/", auth_views.me, name="auth-me"),
    path("auth/logout/", auth_views.logout, name="auth-logout"),
]
