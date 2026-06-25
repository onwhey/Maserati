from django.urls import include, path

urlpatterns = [
    path("api/ops/", include("apps.ops_console.urls")),
]
