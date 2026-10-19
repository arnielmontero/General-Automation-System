from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
    path("mo-close/", include("mo_close.urls")),
]
