from django.urls import path

from . import views

app_name = "habits"

urlpatterns = [
    path("agenda/", views.agenda, name="agenda"),
    path("agenda/horizon/", views.horizon, name="horizon"),
    path("habits/logs/", views.create_log, name="create-log"),
    path("stats/rates/", views.rates, name="rates"),
    path("stats/heatmap/", views.heatmap_view, name="heatmap"),
]
