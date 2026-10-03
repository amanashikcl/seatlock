from django.urls import path

from apps.events.views import EventDetailView, EventListCreateView

urlpatterns = [
    path("", EventListCreateView.as_view(), name="event_list"),
    path("<int:pk>/", EventDetailView.as_view(), name="event_detail"),
]
