from __future__ import annotations

from typing import Any

from django.contrib.auth.password_validation import validate_password as run_validators
from django.db import IntegrityError
from rest_framework import serializers

from apps.accounts.models import User

EMAIL_TAKEN = "A user with this email already exists."


class UserSerializer(serializers.ModelSerializer):
    """Read-only public representation of a user."""

    class Meta:
        model = User
        fields = ["id", "email", "role"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    """Self-service sign-up. Role is NOT accepted: everyone starts as a customer."""

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "email", "password"]
        read_only_fields = ["id"]

    def validate_email(self, value: str) -> str:
        email = value.lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(EMAIL_TAKEN)
        return email

    def validate_password(self, value: str) -> str:
        run_validators(value)  # Django's configured password rules
        return value

    def create(self, validated_data: dict[str, Any]) -> User:
        try:
            return User.objects.create_user(
                email=validated_data["email"], password=validated_data["password"]
            )
        except IntegrityError as exc:  # lost a race with a concurrent sign-up
            raise serializers.ValidationError({"email": [EMAIL_TAKEN]}) from exc


class RoleUpdateSerializer(serializers.ModelSerializer):
    """Admin-only: change a user's role. Nothing else is writable."""

    class Meta:
        model = User
        fields = ["id", "email", "role"]
        read_only_fields = ["id", "email"]
