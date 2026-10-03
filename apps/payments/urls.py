from django.urls import path

from apps.payments import views

urlpatterns = [
    path("webhooks/payments/", views.payment_webhook, name="payment-webhook"),
]
