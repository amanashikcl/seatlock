from django.db import models


class Role(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    ORGANIZER = "organizer", "Organizer"
    ADMIN = "admin", "Admin"
