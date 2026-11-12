from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import (
    IsWorkspaceUser,
    can_view_financials,
    redact_money_fields,
    require_any_user_perm,
    require_perm,
    require_user_perm,
)
from accounts.tenancy import assert_site_access, visible_site_ids
from jobsites.models import Site
from ledger.models import Attachment, Entry, Item
from ledger.serializers import (
    AttachmentSerializer,
    EntrySerializer,
    EntryWriteSerializer,
    ItemSerializer,
)
from ops.models import ActivityLog


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def serialize_entry(entry, request) -> dict:
    data = EntrySerializer(entry).data
    if not can_view_financials(request.user):
        data = redact_money_fields(data)
    return data


class ItemListCreateView(APIView):
    permission_classes = [IsWorkspaceUser]

    def get(self, request):
        # Catalog needed to create entries / manage items / view site work.
        require_any_user_perm(
            request.user,
            ("viewSite", "createEntries", "manageItems"),
        )
        qs = Item.objects.filter(workspace=request.user.workspace)
        t = request.query_params.get("type")
        if t:
            qs = qs.filter(type=t)
        return Response(ItemSerializer(qs, many=True).data)

    def post(self, request):
        require_user_perm(request.user, "manageItems")
        name = (request.data.get("name") or "").strip()
        typ = request.data.get("type")
        if not name or typ not in Item.Type.values:
            return Response({"detail": "type and name required."}, status=400)
        norm = normalize_name(name)
        existing = Item.objects.filter(
            workspace=request.user.workspace, type=typ, normalized=norm
        ).first()
        if existing:
            return Response({"item": ItemSerializer(existing).data, "existed": True})
        item = Item.objects.create(
            workspace=request.user.workspace, type=typ, name=name, normalized=norm
        )
        return Response({"item": ItemSerializer(item).data, "existed": False}, status=201)


class ItemRenameView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageItems")]

    def patch(self, request, pk):
        item = Item.objects.filter(workspace=request.user.workspace, pk=pk).first()
        if not item:
            return Response({"detail": "Not found."}, status=404)
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "name required."}, status=400)
        item.name = name
        item.normalized = normalize_name(name)
        item.save()
        return Response(ItemSerializer(item).data)


class EntryListCreateView(APIView):
    permission_classes = [IsWorkspaceUser]

    def get(self, request):
        require_user_perm(request.user, "viewSite")
        ids = visible_site_ids(request.user)
        qs = Entry.objects.filter(workspace=request.user.workspace, site_id__in=ids).select_related(
            "site", "item"
        ).prefetch_related("attachments")
        site_id = request.query_params.get("siteId") or request.query_params.get("site_id")
        typ = request.query_params.get("type")
        fro = request.query_params.get("from")
        to = request.query_params.get("to")
        q = request.query_params.get("q")
        item_id = request.query_params.get("itemId") or request.query_params.get("item_id")
        staff_id = request.query_params.get("staffId") or request.query_params.get("staff_id")
        if site_id and site_id != "all":
            qs = qs.filter(site_id=site_id)
        if typ and typ != "all":
            if typ == "expenses":
                qs = qs.exclude(type=Entry.Type.PAYMENT)
            else:
                qs = qs.filter(type=typ)
        if fro:
            qs = qs.filter(date__gte=fro)
        if to:
            qs = qs.filter(date__lte=to)
        if item_id:
            qs = qs.filter(item_id=item_id)
        if staff_id:
            qs = qs.filter(created_by_id=staff_id)
        if q:
            qs = qs.filter(description__icontains=q)
        return Response([serialize_entry(e, request) for e in qs[:500]])

    def post(self, request):
        require_user_perm(request.user, "createEntries")
        ser = EntryWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        site = Site.objects.filter(pk=data["site_id"], workspace=request.user.workspace).first()
        if not site:
            return Response({"detail": "Site not found."}, status=404)
        assert_site_access(request.user, site)
        if site.status != Site.Status.ACTIVE:
            return Response({"detail": "Site is not active."}, status=400)
        item = None
        description = data.get("description") or ""
        if data["type"] != Entry.Type.PAYMENT:
            item = Item.objects.filter(
                workspace=request.user.workspace, pk=data.get("item_id")
            ).first()
            if not item:
                return Response({"detail": "Item not found."}, status=400)
            description = item.name
        entry = Entry.objects.create(
            workspace=request.user.workspace,
            site=site,
            type=data["type"],
            item=item,
            description=description,
            quantity=data.get("quantity"),
            unit_price_paise=data.get("unit_price_paise"),
            total_paise=data["total_paise"],
            date=data["date"],
            created_by=request.user,
        )
        attach_ids = data.get("attachment_ids") or []
        if attach_ids:
            Attachment.objects.filter(
                workspace=request.user.workspace, id__in=attach_ids, entry__isnull=True
            ).update(entry=entry)
        request.user.last_site = site
        request.user.save(update_fields=["last_site"])
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action="create",
            target_type="entry",
            target_id=str(entry.id),
            site=site,
            summary=f'Added {entry.type} "{entry.description}"',
            after={"amount": entry.total_paise / 100, "date": str(entry.date)},
        )
        entry = Entry.objects.prefetch_related("attachments").get(pk=entry.pk)
        return Response(serialize_entry(entry, request), status=201)


class EntryDetailView(APIView):
    permission_classes = [IsWorkspaceUser]

    def _get(self, request, pk):
        entry = (
            Entry.objects.filter(workspace=request.user.workspace, pk=pk)
            .select_related("site", "item", "created_by")
            .prefetch_related("attachments")
            .first()
        )
        if not entry:
            return None
        assert_site_access(request.user, entry.site)
        return entry

    def get(self, request, pk):
        require_user_perm(request.user, "viewSite")
        entry = self._get(request, pk)
        if not entry:
            return Response({"detail": "Not found."}, status=404)
        return Response(serialize_entry(entry, request))

    def patch(self, request, pk):
        require_user_perm(request.user, "editEntries")
        entry = self._get(request, pk)
        if not entry:
            return Response({"detail": "Not found."}, status=404)
        payload = {
            "site_id": request.data.get("site_id", entry.site_id),
            "type": request.data.get("type", entry.type),
            "item_id": request.data.get("item_id", entry.item_id),
            "description": request.data.get("description", entry.description),
            "quantity": request.data.get("quantity", entry.quantity),
            "unit_price_paise": request.data.get("unit_price_paise", entry.unit_price_paise),
            "total_paise": request.data.get("total_paise", entry.total_paise),
            "date": request.data.get("date", entry.date),
        }
        ser = EntryWriteSerializer(data=payload)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        before = {"amount": entry.total_paise / 100, "date": str(entry.date)}
        entry.quantity = data.get("quantity")
        entry.unit_price_paise = data.get("unit_price_paise")
        entry.total_paise = data["total_paise"]
        entry.date = data["date"]
        if entry.type != Entry.Type.PAYMENT and data.get("item_id"):
            item = Item.objects.filter(pk=data["item_id"], workspace=request.user.workspace).first()
            if item:
                entry.item = item
                entry.description = item.name
        elif entry.type == Entry.Type.PAYMENT and data.get("description"):
            entry.description = data["description"]
        entry.save()
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action="update",
            target_type="entry",
            target_id=str(entry.id),
            site=entry.site,
            summary=f'Edited entry "{entry.description}"',
            before=before,
            after={"amount": entry.total_paise / 100, "date": str(entry.date)},
        )
        return Response(serialize_entry(entry, request))

    def delete(self, request, pk):
        require_user_perm(request.user, "editEntries")
        entry = self._get(request, pk)
        if not entry:
            return Response({"detail": "Not found."}, status=404)
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action="delete",
            target_type="entry",
            target_id=str(entry.id),
            site=entry.site,
            summary=f'Deleted entry "{entry.description}"',
            before={"amount": entry.total_paise / 100, "date": str(entry.date)},
        )
        entry.delete()
        return Response(status=204)


class MediaListUploadView(APIView):
    permission_classes = [IsWorkspaceUser]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        require_user_perm(request.user, "viewSite")
        ids = visible_site_ids(request.user)
        qs = Attachment.objects.filter(
            workspace=request.user.workspace, site_id__in=ids
        ).select_related("site", "entry", "created_by")
        site_id = request.query_params.get("siteId") or request.query_params.get("site_id")
        kind = request.query_params.get("kind")
        fro = request.query_params.get("from")
        to = request.query_params.get("to")
        if site_id and site_id != "all":
            qs = qs.filter(site_id=site_id)
        if kind:
            qs = qs.filter(kind=kind)
        if fro:
            qs = qs.filter(date__gte=fro)
        if to:
            qs = qs.filter(date__lte=to)
        # Bills are financial documents — hide without viewFinancials.
        if not can_view_financials(request.user):
            if kind == Attachment.Kind.BILL:
                return Response({"detail": "Missing permission: viewFinancials."}, status=403)
            qs = qs.exclude(kind=Attachment.Kind.BILL)
        return Response(
            AttachmentSerializer(qs[:500], many=True, context={"request": request}).data
        )

    def post(self, request):
        require_user_perm(request.user, "uploadMedia")
        site_id = request.data.get("siteId") or request.data.get("site_id")
        kind = request.data.get("kind")
        date = request.data.get("date")
        caption = request.data.get("caption") or ""
        f = request.FILES.get("file")
        if not (site_id and kind and date and f):
            return Response({"detail": "file, siteId, kind, date required."}, status=400)
        if kind not in Attachment.Kind.values:
            return Response({"detail": "Invalid kind."}, status=400)
        if kind == Attachment.Kind.BILL and not can_view_financials(request.user):
            return Response({"detail": "Missing permission: viewFinancials."}, status=403)
        site = Site.objects.filter(pk=site_id, workspace=request.user.workspace).first()
        if not site:
            return Response({"detail": "Site not found."}, status=404)
        assert_site_access(request.user, site)
        if site.status != Site.Status.ACTIVE:
            return Response({"detail": "Site is not active."}, status=400)
        att = Attachment.objects.create(
            workspace=request.user.workspace,
            site=site,
            kind=kind,
            name=f.name,
            size_bytes=f.size,
            file=f,
            caption=caption[:80],
            date=date,
            created_by=request.user,
        )
        if kind == Attachment.Kind.PHOTO:
            ActivityLog.objects.create(
                workspace=request.user.workspace,
                actor=request.user,
                action="create",
                target_type="photo",
                target_id=str(att.id),
                site=site,
                summary=f'Uploaded progress photo{f" “{caption}”" if caption else ""}',
            )
        return Response(
            AttachmentSerializer(att, context={"request": request}).data, status=201
        )


class MediaDeleteView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("uploadMedia")]

    def delete(self, request, pk):
        att = Attachment.objects.filter(workspace=request.user.workspace, pk=pk).first()
        if not att:
            return Response({"detail": "Not found."}, status=404)
        assert_site_access(request.user, att.site)
        if att.kind == Attachment.Kind.BILL and not can_view_financials(request.user):
            return Response({"detail": "Missing permission: viewFinancials."}, status=403)
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action="delete",
            target_type="photo" if att.kind == Attachment.Kind.PHOTO else "entry",
            target_id=str(att.id),
            site=att.site,
            summary=f"Removed {att.kind} {att.caption or att.name}",
        )
        att.file.delete(save=False)
        att.delete()
        return Response(status=204)
