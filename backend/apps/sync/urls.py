from django.urls import path

from . import views

app_name = "sync"

urlpatterns = [
    path("pull/", views.pull, name="pull"),
    path("push/", views.push, name="push"),
]
