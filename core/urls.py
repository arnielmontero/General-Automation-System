from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("health", views.health, name="health"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/", views.user_update, name="user_update"),
    path("logs/", views.logs, name="logs"),
]
