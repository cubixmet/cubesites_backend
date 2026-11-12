from django.contrib.auth import authenticate
from rest_framework import serializers

from accounts.models import User, Workspace, default_permissions
from accounts.permissions import sanitize_permissions
from jobsites.models import SiteAssignment


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = (
            "id",
            "business_name",
            "owner_name",
            "phone",
            "email",
            "district",
            "gstin",
            "status",
            "tax_label",
            "tax_rate_pct",
            "show_tax_breakup",
            "drive_status",
            "drive_email",
            "drive_last_backup_at",
            "notify_daily_summary",
            "notify_payment_received",
            "notify_backup_failure",
            "notify_invoice_due",
            "created_at",
            "last_activity_at",
        )
        read_only_fields = (
            "id",
            "status",
            "created_at",
            "last_activity_at",
            "drive_status",
            "drive_email",
            "drive_last_backup_at",
        )


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    site_ids = serializers.SerializerMethodField()
    active = serializers.BooleanField(source="is_active")

    class Meta:
        model = User
        fields = (
            "id",
            "name",
            "email",
            "phone",
            "role",
            "active",
            "permissions",
            "site_ids",
            "is_platform_admin",
            "date_joined",
        )
        read_only_fields = fields

    def get_name(self, obj):
        return obj.display_name

    def get_site_ids(self, obj):
        # Use prefetched reverse relation when available (staff/admin lists).
        # Avoid SiteAssignment.objects.filter(...) which causes N+1 on list endpoints.
        # Stable order so prefetch vs non-prefetch return the same sequence.
        cache = getattr(obj, "_prefetched_objects_cache", None)
        if cache is not None and "site_assignments" in cache:
            rows = sorted(
                obj.site_assignments.all(),
                key=lambda a: (a.created_at.isoformat() if a.created_at else "", str(a.pk)),
            )
            return [str(a.site_id) for a in rows]
        return [
            str(x)
            for x in SiteAssignment.objects.filter(user_id=obj.pk)
            .order_by("created_at", "id")
            .values_list("site_id", flat=True)
        ]

    @staticmethod
    def setup_eager_loading(queryset):
        """Apply on staff/user list/detail GET querysets."""
        return queryset.prefetch_related("site_assignments")


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        ident = attrs["identifier"].strip()
        password = attrs["password"]
        user = None
        if "@" in ident:
            user = User.objects.filter(email__iexact=ident).first()
        else:
            digits = "".join(c for c in ident if c.isdigit())
            if len(digits) >= 10:
                user = User.objects.filter(phone__endswith=digits[-10:]).first()
        if not user:
            # try username
            user = authenticate(
                request=self.context.get("request"),
                username=ident,
                password=password,
            )
            if user:
                attrs["user"] = user
                return attrs
            raise serializers.ValidationError({"detail": "Invalid credentials."})
        if not user.check_password(password):
            raise serializers.ValidationError({"detail": "Invalid credentials."})
        if not user.is_active:
            raise serializers.ValidationError({"detail": "This account is disabled."})
        if user.workspace_id and user.workspace.status == Workspace.Status.SUSPENDED:
            raise serializers.ValidationError({"detail": "Workspace is suspended."})
        attrs["user"] = user
        return attrs


class StaffWriteSerializer(serializers.ModelSerializer):
    name = serializers.CharField(write_only=True)
    active = serializers.BooleanField(source="is_active", required=False, default=True)
    site_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = (
            "id",
            "name",
            "email",
            "phone",
            "role",
            "active",
            "permissions",
            "site_ids",
            "password",
        )
        read_only_fields = ("id",)

    def validate_role(self, value):
        if value == User.Role.OWNER:
            raise serializers.ValidationError("Cannot create another owner via staff API.")
        return value

    def validate_permissions(self, value):
        return sanitize_permissions(value)

    def create(self, validated):
        name = validated.pop("name")
        site_ids = validated.pop("site_ids", [])
        password = validated.pop("password", "") or "demo1234"
        first, *rest = name.split(" ", 1)
        perms = validated.get("permissions")
        if not perms:
            perms = sanitize_permissions(default_permissions(validated["role"]))
        else:
            perms = sanitize_permissions(perms)
        user = User(
            workspace=self.context["workspace"],
            username=validated["email"],
            email=validated["email"],
            phone=validated.get("phone", ""),
            role=validated["role"],
            is_active=validated.get("is_active", True),
            permissions=perms,
            first_name=first,
            last_name=rest[0] if rest else "",
            email_verified=True,
            auth_provider="password",
        )
        user.set_password(password)
        user.save()
        self._set_sites(user, site_ids)
        return user

    def update(self, instance, validated):
        name = validated.pop("name", None)
        site_ids = validated.pop("site_ids", None)
        password = validated.pop("password", None)
        if name is not None:
            first, *rest = name.split(" ", 1)
            instance.first_name = first
            instance.last_name = rest[0] if rest else ""
        if "permissions" in validated:
            validated["permissions"] = sanitize_permissions(validated["permissions"])
        for k, v in validated.items():
            setattr(instance, k, v)
        if password:
            instance.set_password(password)
        instance.save()
        if site_ids is not None:
            self._set_sites(instance, site_ids)
        return instance

    def _set_sites(self, user, site_ids):
        from jobsites.models import Site, SiteAssignment

        SiteAssignment.objects.filter(user=user).delete()
        sites = Site.objects.filter(workspace=user.workspace, id__in=site_ids)
        SiteAssignment.objects.bulk_create(
            [SiteAssignment(site=s, user=user) for s in sites]
        )


class MeUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    phone = serializers.CharField(required=False, allow_blank=True)

    def update(self, instance, validated):
        if "name" in validated:
            first, *rest = validated["name"].split(" ", 1)
            instance.first_name = first
            instance.last_name = rest[0] if rest else ""
        if "phone" in validated:
            instance.phone = validated["phone"]
        instance.save()
        return instance
