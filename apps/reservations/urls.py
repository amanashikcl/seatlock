from django.urls import path

from apps.reservations.views import EventSeatListView, HoldSeatsView

urlpatterns = [
    path("<int:event_id>/seats/", EventSeatListView.as_view(), name="event_seats"),
    path("<int:event_id>/holds/", HoldSeatsView.as_view(), name="event_holds"),
]
