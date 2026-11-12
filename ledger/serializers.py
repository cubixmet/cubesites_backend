from rest_framework import serializers

from ledger.models import Attachment, Entry, Item
from ledger.money import parse_qty, total_from


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = ("id", "type", "name", "normalized", "created_at")
        read_only_fields = ("id", "normalized", "created_at")


class EntrySerializer(serializers.ModelSerializer):
    site_id = serializers.UUIDField(read_only=True)
    item_id = serializers.UUIDField(read_only=True, allow_null=True)
    attachment_ids = serializers.SerializerMethodField()
    created_by = serializers.UUIDField(source="created_by_id", allow_null=True, read_only=True)

    class Meta:
        model = Entry
        fields = (
            "id",
            "site_id",
            "type",
            "item_id",
            "description",
            "quantity",
            "unit_price_paise",
            "total_paise",
            "date",
            "attachment_ids",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at", "attachment_ids")

    def get_attachment_ids(self, obj):
        return [str(a.id) for a in obj.attachments.all()]


class EntryWriteSerializer(serializers.Serializer):
    site_id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=Entry.Type.choices)
    item_id = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, required=False, allow_null=True)
    unit_price_paise = serializers.IntegerField(required=False, allow_null=True)
    total_paise = serializers.IntegerField(required=False, allow_null=True)
    date = serializers.DateField()
    attachment_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)

    def validate(self, attrs):
        etype = attrs["type"]
        if etype != Entry.Type.PAYMENT and not attrs.get("item_id"):
            raise serializers.ValidationError({"item_id": "Select an item."})
        qty = attrs.get("quantity")
        unit = attrs.get("unit_price_paise")
        total = attrs.get("total_paise")
        if qty is not None and unit is not None and total is None:
            attrs["total_paise"] = total_from(qty, unit)
        if not attrs.get("total_paise") or attrs["total_paise"] <= 0:
            raise serializers.ValidationError({"total_paise": "Amount must be greater than zero."})
        return attrs


class AttachmentSerializer(serializers.ModelSerializer):
    site_id = serializers.UUIDField(read_only=True)
    entry_id = serializers.UUIDField(read_only=True, allow_null=True)
    src = serializers.SerializerMethodField()
    created_by = serializers.UUIDField(source="created_by_id", allow_null=True, read_only=True)

    class Meta:
        model = Attachment
        fields = (
            "id",
            "site_id",
            "entry_id",
            "kind",
            "name",
            "size_bytes",
            "src",
            "caption",
            "date",
            "created_by",
            "created_at",
        )

    def get_src(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        if obj.file:
            return obj.file.url
        return ""
