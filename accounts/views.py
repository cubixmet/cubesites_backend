from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from accounts.permissions import IsWorkspaceUser, require_perm
from accounts.serializers import (
    MeUpdateSerializer,
    StaffWriteSerializer,
    UserSerializer,
    WorkspaceSerializer,
)
from ops.models import ActivityLog


def tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class MeView(APIView):
    def get(self, request):
        user = request.user
        if user.workspace_id:
            # Prefetch assignments so site_ids does not issue an extra query.
            user = UserSerializer.setup_eager_loading(
                User.objects.filter(pk=user.pk)
            ).select_related("workspace").get()
        return Response(
            {
                "user": UserSerializer(user).data,
                "workspace": WorkspaceSerializer(user.workspace).data
                if user.workspace_id
                else None,
            }
        )

    def patch(self, request):
        ser = MeUpdateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.update(request.user, ser.validated_data)
        return Response(UserSerializer(request.user).data)


class WorkspaceDetailView(APIView):
    permission_classes = [IsWorkspaceUser]

    def get(self, request):
        return Response(WorkspaceSerializer(request.user.workspace).data)

    def patch(self, request):
        if not request.user.has_perm_key("manageStaffSites"):
            return Response({"detail": "Permission denied."}, status=403)
        ser = WorkspaceSerializer(request.user.workspace, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


class StaffListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]
    serializer_class = StaffWriteSerializer
    pagination_class = None

    def get_queryset(self):
        qs = User.objects.filter(workspace=self.request.user.workspace).exclude(
            role=User.Role.OWNER
        )
        return UserSerializer.setup_eager_loading(qs)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["workspace"] = self.request.user.workspace
        return ctx

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        return Response(UserSerializer(qs, many=True).data)

    def perform_create(self, serializer):
        user = serializer.save()
        ActivityLog.objects.create(
            workspace=request_workspace(self.request),
            actor=self.request.user,
            action="create",
            target_type="staff",
            target_id=str(user.id),
            summary=f"Added staff {user.display_name} ({user.role})",
        )


class StaffDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]
    serializer_class = StaffWriteSerializer
    lookup_field = "pk"

    def get_queryset(self):
        qs = User.objects.filter(workspace=self.request.user.workspace).exclude(
            role=User.Role.OWNER
        )
        return UserSerializer.setup_eager_loading(qs)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["workspace"] = self.request.user.workspace
        return ctx

    def retrieve(self, request, *args, **kwargs):
        return Response(UserSerializer(self.get_object()).data)


class StaffActiveView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def post(self, request, pk):
        user = (
            UserSerializer.setup_eager_loading(
                User.objects.filter(workspace=request.user.workspace, pk=pk).exclude(
                    role=User.Role.OWNER
                )
            )
            .first()
        )
        if not user:
            return Response({"detail": "Not found."}, status=404)
        active = bool(request.data.get("active", True))
        user.is_active = active
        user.save(update_fields=["is_active"])
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action="deactivate" if not active else "reactivate",
            target_type="staff",
            target_id=str(user.id),
            summary=f"{'Disabled' if not active else 'Enabled'} staff {user.display_name}",
        )
        return Response(UserSerializer(user).data)


def request_workspace(request):
    return request.user.workspace
