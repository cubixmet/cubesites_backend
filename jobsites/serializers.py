from rest_framework import serializers

from jobsites.models import Site, SiteStatusEvent


class SiteStatusEventSerializer(serializers.ModelSerializer):
    by = serializers.UUIDField(source="by_id", allow_null=True)

    class Meta:
        model = SiteStatusEvent
        fields = ("status", "at", "by")


class SiteSerializer(serializers.ModelSerializer):
    status_history = SiteStatusEventSerializer(many=True, read_only=True)
    primary_phone = serializers.CharField()
    alt_phone = serializers.CharField(required=False, allow_blank=True)
    start_date = serializers.DateField(required=False)

    class Meta:
        model = Site
        fields = (
            "id",
            "name",
            "primary_phone",
            "alt_phone",
            "address",
            "status",
            "start_date",
            "status_history",
            "created_at",
        )
        read_only_fields = ("id", "status", "status_history", "created_at")

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Site name is required.")
        if "<" in name or ">" in name:
            raise serializers.ValidationError("Site name cannot contain < or > characters.")
        return name

    def validate_primary_phone(self, value):
        digits = "".join(c for c in value if c.isdigit())
        if len(digits) < 10:
            raise serializers.ValidationError("Enter a valid phone number.")
        return value
