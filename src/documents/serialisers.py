import datetime
import logging
import math
import re
import zoneinfo
from collections.abc import Iterable
from decimal import Decimal

import magic
from celery import states
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.validators import DecimalValidator
from django.core.validators import MaxLengthValidator
from django.core.validators import RegexValidator
from django.core.validators import integer_validator
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.utils.translation import gettext as _
from drf_writable_nested.serializers import NestedUpdateMixin
from guardian.core import ObjectPermissionChecker
from guardian.shortcuts import get_users_with_perms
from guardian.utils import get_group_obj_perms_model
from guardian.utils import get_user_obj_perms_model
from rest_framework import fields
from rest_framework import serializers
from rest_framework.fields import SerializerMethodField

if settings.AUDIT_LOG_ENABLED:
    from auditlog.context import set_actor

from documents import bulk_edit
from documents.data_models import DocumentSource
from documents.models import ArchiveSerialNumberPrefix
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import MatchingModel
from documents.models import PaperlessTask
from documents.models import SavedView
from documents.models import SavedViewFilterRule
from documents.models import ShareLink
from documents.models import StoragePath
from documents.models import Tag
from documents.models import UiSettings
from documents.models import Workflow
from documents.models import WorkflowAction
from documents.models import WorkflowActionEmail
from documents.models import WorkflowActionWebhook
from documents.models import WorkflowTrigger
from documents.parsers import is_mime_type_supported
from documents.permissions import get_groups_with_only_permission
from documents.permissions import set_permissions_for_object
from documents.templating.filepath import validate_filepath_template_and_render
from documents.templating.utils import convert_format_str_to_template_format
from documents.validators import uri_validator

logger = logging.getLogger("paperless.serializers")


# https://www.django-rest-framework.org/api-guide/serializers/#example
class DynamicFieldsModelSerializer(serializers.ModelSerializer):
    """
    A ModelSerializer that takes an additional `fields` argument that
    controls which fields should be displayed.
    """

    def __init__(self, *args, **kwargs):
        # Don't pass the 'fields' arg up to the superclass
        fields = kwargs.pop("fields", None)

        # Instantiate the superclass normally
        super().__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)


class MatchingModelSerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(read_only=True)

    def get_slug(self, obj):
        return slugify(obj.name)

    slug = SerializerMethodField()

    def validate(self, data):
        # TODO: remove pending https://github.com/encode/django-rest-framework/issues/7173
        name = data.get(
            "name",
            self.instance.name if hasattr(self.instance, "name") else None,
        )
        owner = (
            data["owner"]
            if "owner" in data
            else self.user
            if hasattr(self, "user")
            else None
        )
        pk = self.instance.pk if hasattr(self.instance, "pk") else None
        if ("name" in data or "owner" in data) and self.Meta.model.objects.filter(
            name=name,
            owner=owner,
        ).exclude(pk=pk).exists():
            raise serializers.ValidationError(
                {"error": "Object violates owner / name unique constraint"},
            )
        return data

    def validate_match(self, match):
        if (
            "matching_algorithm" in self.initial_data
            and self.initial_data["matching_algorithm"] == MatchingModel.MATCH_REGEX
        ):
            try:
                re.compile(match)
            except re.error as e:
                raise serializers.ValidationError(
                    _("Invalid regular expression: %(error)s") % {"error": str(e.msg)},
                )
        return match


class SetPermissionsMixin:
    def _validate_user_ids(self, user_ids):
        users = User.objects.none()
        if user_ids is not None:
            users = User.objects.filter(id__in=user_ids)
            if not users.count() == len(user_ids):
                raise serializers.ValidationError(
                    "Some users in don't exist or were specified twice.",
                )
        return users

    def _validate_group_ids(self, group_ids):
        groups = Group.objects.none()
        if group_ids is not None:
            groups = Group.objects.filter(id__in=group_ids)
            if not groups.count() == len(group_ids):
                raise serializers.ValidationError(
                    "Some groups in don't exist or were specified twice.",
                )
        return groups

    def validate_set_permissions(self, set_permissions=None):
        permissions_dict = {
            "view": {
                "users": User.objects.none(),
                "groups": Group.objects.none(),
            },
            "change": {
                "users": User.objects.none(),
                "groups": Group.objects.none(),
            },
        }
        if set_permissions is not None:
            for action, _ in permissions_dict.items():
                if action in set_permissions:
                    users = set_permissions[action]["users"]
                    permissions_dict[action]["users"] = self._validate_user_ids(users)
                    groups = set_permissions[action]["groups"]
                    permissions_dict[action]["groups"] = self._validate_group_ids(
                        groups,
                    )
        return permissions_dict

    def _set_permissions(self, permissions, object):
        set_permissions_for_object(permissions, object)


class SerializerWithPerms(serializers.Serializer):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.full_perms = kwargs.pop("full_perms", False)
        super().__init__(*args, **kwargs)


class OwnedObjectSerializer(
    SerializerWithPerms,
    serializers.ModelSerializer,
    SetPermissionsMixin,
):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        try:
            if self.full_perms:
                self.fields.pop("user_can_change")
                self.fields.pop("is_shared_by_requester")
            else:
                self.fields.pop("permissions")
        except KeyError:
            pass

    def get_permissions(self, obj):
        view_codename = f"view_{obj.__class__.__name__.lower()}"
        change_codename = f"change_{obj.__class__.__name__.lower()}"

        return {
            "view": {
                "users": get_users_with_perms(
                    obj,
                    only_with_perms_in=[view_codename],
                    with_group_users=False,
                ).values_list("id", flat=True),
                "groups": get_groups_with_only_permission(
                    obj,
                    codename=view_codename,
                ).values_list("id", flat=True),
            },
            "change": {
                "users": get_users_with_perms(
                    obj,
                    only_with_perms_in=[change_codename],
                    with_group_users=False,
                ).values_list("id", flat=True),
                "groups": get_groups_with_only_permission(
                    obj,
                    codename=change_codename,
                ).values_list("id", flat=True),
            },
        }

    def get_user_can_change(self, obj):
        checker = ObjectPermissionChecker(self.user) if self.user is not None else None
        return (
            obj.owner is None
            or obj.owner == self.user
            or (
                self.user is not None
                and checker.has_perm(f"change_{obj.__class__.__name__.lower()}", obj)
            )
        )

    @staticmethod
    def get_shared_object_pks(objects: Iterable):
        """
        Return the primary keys of the subset of objects that are shared.
        """
        try:
            first_obj = next(iter(objects))
        except StopIteration:
            return set()

        ctype = ContentType.objects.get_for_model(first_obj)
        object_pks = list(obj.pk for obj in objects)
        pk_type = type(first_obj.pk)

        def get_pks_for_permission_type(model):
            return map(
                pk_type,  # coerce the pk to be the same type of the provided objects
                model.objects.filter(
                    content_type=ctype,
                    object_pk__in=object_pks,
                )
                .values_list("object_pk", flat=True)
                .distinct(),
            )

        UserObjectPermission = get_user_obj_perms_model()
        GroupObjectPermission = get_group_obj_perms_model()
        user_permission_pks = get_pks_for_permission_type(UserObjectPermission)
        group_permission_pks = get_pks_for_permission_type(GroupObjectPermission)

        return set(user_permission_pks) | set(group_permission_pks)

    def get_is_shared_by_requester(self, obj: Document):
        # First check the context to see if `shared_object_pks` is set by the parent.
        shared_object_pks = self.context.get("shared_object_pks")
        # If not just check if the current object is shared.
        if shared_object_pks is None:
            shared_object_pks = self.get_shared_object_pks([obj])
        return obj.owner == self.user and obj.id in shared_object_pks

    permissions = SerializerMethodField(read_only=True)
    user_can_change = SerializerMethodField(read_only=True)
    is_shared_by_requester = SerializerMethodField(read_only=True)

    set_permissions = serializers.DictField(
        label="Set permissions",
        allow_empty=True,
        required=False,
        write_only=True,
    )
    # other methods in mixin

    def validate_unique_together(self, validated_data, instance=None):
        # workaround for https://github.com/encode/django-rest-framework/issues/9358
        if "owner" in validated_data and "name" in self.Meta.fields:
            name = validated_data.get("name", instance.name if instance else None)
            objects = (
                self.Meta.model.objects.exclude(pk=instance.pk)
                if instance
                else self.Meta.model.objects.all()
            )
            not_unique = objects.filter(
                owner=validated_data["owner"],
                name=name,
            ).exists()
            if not_unique:
                raise serializers.ValidationError(
                    {"error": "Object violates owner / name unique constraint"},
                )

    def create(self, validated_data):
        # default to current user if not set
        request = self.context.get("request")
        if (
            "owner" not in validated_data
            or (request is not None and "owner" not in request.data)
        ) and self.user:
            validated_data["owner"] = self.user
        permissions = None
        if "set_permissions" in validated_data:
            permissions = validated_data.pop("set_permissions")
        self.validate_unique_together(validated_data)
        instance = super().create(validated_data)
        if permissions is not None:
            self._set_permissions(permissions, instance)
        return instance

    def update(self, instance, validated_data):
        if "set_permissions" in validated_data:
            self._set_permissions(validated_data["set_permissions"], instance)
        self.validate_unique_together(validated_data, instance)
        return super().update(instance, validated_data)


class OwnedObjectListSerializer(serializers.ListSerializer):
    def to_representation(self, documents):
        self.child.context["shared_object_pks"] = self.child.get_shared_object_pks(
            documents,
        )
        return super().to_representation(documents)



class ArchiveSerialNumberPrefixSerializer(MatchingModelSerializer, OwnedObjectSerializer):
    class Meta:
        model = ArchiveSerialNumberPrefix
        fields = (
            "id",
            "slug",
            "name",
            "document_count",
            "owner",
            "permissions",
            "user_can_change",
            "set_permissions",
        )


class CorrespondentSerializer(MatchingModelSerializer, OwnedObjectSerializer):
    last_correspondence = serializers.DateTimeField(read_only=True, required=False)

    class Meta:
        model = Correspondent
        fields = (
            "id",
            "slug",
            "name",
            "match",
            "matching_algorithm",
            "is_insensitive",
            "document_count",
            "last_correspondence",
            "owner",
            "permissions",
            "user_can_change",
            "set_permissions",
        )

class DocumentTypeSerializer(MatchingModelSerializer, OwnedObjectSerializer):
    class Meta:
        model = DocumentType
        fields = (
            "id",
            "slug",
            "name",
            "match",
            "matching_algorithm",
            "is_insensitive",
            "document_count",
            "owner",
            "permissions",
            "user_can_change",
            "set_permissions",
        )


class ColorField(serializers.Field):
    COLOURS = (
        (1, "#a6cee3"),
        (2, "#1f78b4"),
        (3, "#b2df8a"),
        (4, "#33a02c"),
        (5, "#fb9a99"),
        (6, "#e31a1c"),
        (7, "#fdbf6f"),
        (8, "#ff7f00"),
        (9, "#cab2d6"),
        (10, "#6a3d9a"),
        (11, "#b15928"),
        (12, "#000000"),
        (13, "#cccccc"),
    )

    def to_internal_value(self, data):
        for id, color in self.COLOURS:
            if id == data:
                return color
        raise serializers.ValidationError

    def to_representation(self, value):
        for id, color in self.COLOURS:
            if color == value:
                return id
        return 1


class TagSerializerVersion1(MatchingModelSerializer, OwnedObjectSerializer):
    colour = ColorField(source="color", default="#a6cee3")

    class Meta:
        model = Tag
        fields = (
            "id",
            "slug",
            "name",
            "colour",
            "match",
            "matching_algorithm",
            "is_insensitive",
            "is_inbox_tag",
            "document_count",
            "owner",
            "permissions",
            "user_can_change",
            "set_permissions",
        )


class TagSerializer(MatchingModelSerializer, OwnedObjectSerializer):
    def get_text_color(self, obj):
        try:
            h = obj.color.lstrip("#")
            rgb = tuple(int(h[i : i + 2], 16) / 256 for i in (0, 2, 4))
            luminance = math.sqrt(
                0.299 * math.pow(rgb[0], 2)
                + 0.587 * math.pow(rgb[1], 2)
                + 0.114 * math.pow(rgb[2], 2),
            )
            return "#ffffff" if luminance < 0.53 else "#000000"
        except ValueError:
            return "#000000"

    text_color = serializers.SerializerMethodField()

    class Meta:
        model = Tag
        fields = (
            "id",
            "slug",
            "name",
            "color",
            "text_color",
            "match",
            "matching_algorithm",
            "is_insensitive",
            "is_inbox_tag",
            "document_count",
            "owner",
            "permissions",
            "user_can_change",
            "set_permissions",
        )

    def validate_color(self, color):
        regex = r"#[0-9a-fA-F]{6}"
        if not re.match(regex, color):
            raise serializers.ValidationError(_("Invalid color."))
        return color

class ArchiveSerialNumberPrefixField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return ArchiveSerialNumberPrefix.objects.all()

class CorrespondentField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Correspondent.objects.all()


class TagsField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Tag.objects.all()


class DocumentTypeField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return DocumentType.objects.all()


class StoragePathField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return StoragePath.objects.all()


class CustomFieldSerializer(serializers.ModelSerializer):
    data_type = serializers.ChoiceField(
        choices=CustomField.FieldDataType,
        read_only=False,
    )

    document_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = CustomField
        fields = [
            "id",
            "name",
            "data_type",
            "extra_data",
            "document_count",
        ]

    def validate(self, attrs):
        # TODO: remove pending https://github.com/encode/django-rest-framework/issues/7173
        name = attrs.get(
            "name",
            self.instance.name if hasattr(self.instance, "name") else None,
        )
        objects = (
            self.Meta.model.objects.exclude(
                pk=self.instance.pk,
            )
            if self.instance is not None
            else self.Meta.model.objects.all()
        )
        if ("name" in attrs) and objects.filter(
            name=name,
        ).exists():
            raise serializers.ValidationError(
                {"error": "Object violates name unique constraint"},
            )
        if (
            "data_type" in attrs
            and attrs["data_type"] == CustomField.FieldDataType.SELECT
        ) or (
            self.instance
            and self.instance.data_type == CustomField.FieldDataType.SELECT
        ):
            if (
                "extra_data" not in attrs
                or "select_options" not in attrs["extra_data"]
                or not isinstance(attrs["extra_data"]["select_options"], list)
                or len(attrs["extra_data"]["select_options"]) == 0
                or not all(
                    len(option.get("label", "")) > 0
                    for option in attrs["extra_data"]["select_options"]
                )
            ):
                raise serializers.ValidationError(
                    {"error": "extra_data.select_options must be a valid list"},
                )
            # labels are valid, generate ids if not present
            for option in attrs["extra_data"]["select_options"]:
                if option.get("id") is None:
                    option["id"] = get_random_string(length=16)
        elif (
            "data_type" in attrs
            and attrs["data_type"] == CustomField.FieldDataType.MONETARY
            and "extra_data" in attrs
            and "default_currency" in attrs["extra_data"]
            and attrs["extra_data"]["default_currency"] is not None
            and (
                not isinstance(attrs["extra_data"]["default_currency"], str)
                or (
                    len(attrs["extra_data"]["default_currency"]) > 0
                    and len(attrs["extra_data"]["default_currency"]) != 3
                )
            )
        ):
            raise serializers.ValidationError(
                {"error": "extra_data.default_currency must be a 3-character string"},
            )
        return super().validate(attrs)


class ReadWriteSerializerMethodField(serializers.SerializerMethodField):
    """
    Based on https://stackoverflow.com/a/62579804
    """

    def __init__(self, method_name=None, *args, **kwargs):
        self.method_name = method_name
        kwargs["source"] = "*"
        super(serializers.SerializerMethodField, self).__init__(*args, **kwargs)

    def to_internal_value(self, data):
        return {self.field_name: data}


class CustomFieldInstanceSerializer(serializers.ModelSerializer):
    field = serializers.PrimaryKeyRelatedField(queryset=CustomField.objects.all())
    value = ReadWriteSerializerMethodField(allow_null=True)

    def create(self, validated_data):
        # An instance is attached to a document
        document: Document = validated_data["document"]
        # And to a CustomField
        custom_field: CustomField = validated_data["field"]
        # This key must exist, as it is validated
        data_store_name = CustomFieldInstance.get_value_field_name(
            custom_field.data_type,
        )

        if custom_field.data_type == CustomField.FieldDataType.DOCUMENTLINK:
            # prior to update so we can look for any docs that are going to be removed
            self.reflect_doclinks(document, custom_field, validated_data["value"])

        # Actually update or create the instance, providing the value
        # to fill in the correct attribute based on the type
        instance, _ = CustomFieldInstance.objects.update_or_create(
            document=document,
            field=custom_field,
            defaults={data_store_name: validated_data["value"]},
        )
        return instance

    def get_value(self, obj: CustomFieldInstance):
        return obj.value

    def validate(self, data):
        """
        Probably because we're kind of doing it odd, validation from the model
        doesn't run against the field "value", so we have to re-create it here.

        Don't like it, but it is better than returning an HTTP 500 when the database
        hates the value
        """
        data = super().validate(data)
        field: CustomField = data["field"]
        if "value" in data and data["value"] is not None:
            if (
                field.data_type == CustomField.FieldDataType.URL
                and len(data["value"]) > 0
            ):
                uri_validator(data["value"])
            elif field.data_type == CustomField.FieldDataType.INT:
                integer_validator(data["value"])
            elif (
                field.data_type == CustomField.FieldDataType.MONETARY
                and data["value"] != ""
            ):
                try:
                    # First try to validate as a number from legacy format
                    DecimalValidator(max_digits=12, decimal_places=2)(
                        Decimal(str(data["value"])),
                    )
                except Exception:
                    # If that fails, try to validate as a monetary string
                    RegexValidator(
                        regex=r"^[A-Z]{3}-?\d+(\.\d{1,2})$",
                        message="Must be a two-decimal number with optional currency code e.g. GBP123.45",
                    )(data["value"])
            elif field.data_type == CustomField.FieldDataType.STRING:
                MaxLengthValidator(limit_value=128)(data["value"])
            elif field.data_type == CustomField.FieldDataType.SELECT:
                select_options = field.extra_data["select_options"]
                try:
                    next(
                        option
                        for option in select_options
                        if option["id"] == data["value"]
                    )
                except Exception:
                    raise serializers.ValidationError(
                        f"Value must be an id of an element in {select_options}",
                    )
            elif field.data_type == CustomField.FieldDataType.DOCUMENTLINK:
                if not (isinstance(data["value"], list) or data["value"] is None):
                    raise serializers.ValidationError(
                        "Value must be a list",
                    )
                doc_ids = data["value"]
                if Document.objects.filter(id__in=doc_ids).count() != len(
                    data["value"],
                ):
                    raise serializers.ValidationError(
                        "Some documents in value don't exist or were specified twice.",
                    )

        return data

    def reflect_doclinks(
        self,
        document: Document,
        field: CustomField,
        target_doc_ids: list[int],
    ):
        """
        Add or remove 'symmetrical' links to `document` on all `target_doc_ids`
        """

        if target_doc_ids is None:
            target_doc_ids = []

        # Check if any documents are going to be removed from the current list of links and remove the symmetrical links
        current_field_instance = CustomFieldInstance.objects.filter(
            field=field,
            document=document,
        ).first()
        if (
            current_field_instance is not None
            and current_field_instance.value is not None
        ):
            for doc_id in current_field_instance.value:
                if doc_id not in target_doc_ids:
                    self.remove_doclink(document, field, doc_id)

        # Create an instance if target doc doesn't have this field or append it to an existing one
        existing_custom_field_instances = {
            custom_field.document_id: custom_field
            for custom_field in CustomFieldInstance.objects.filter(
                field=field,
                document_id__in=target_doc_ids,
            )
        }
        custom_field_instances_to_create = []
        custom_field_instances_to_update = []
        for target_doc_id in target_doc_ids:
            target_doc_field_instance = existing_custom_field_instances.get(
                target_doc_id,
            )
            if target_doc_field_instance is None:
                custom_field_instances_to_create.append(
                    CustomFieldInstance(
                        document_id=target_doc_id,
                        field=field,
                        value_document_ids=[document.id],
                    ),
                )
            elif target_doc_field_instance.value is None:
                target_doc_field_instance.value_document_ids = [document.id]
                custom_field_instances_to_update.append(target_doc_field_instance)
            elif document.id not in target_doc_field_instance.value:
                target_doc_field_instance.value_document_ids.append(document.id)
                custom_field_instances_to_update.append(target_doc_field_instance)

        CustomFieldInstance.objects.bulk_create(custom_field_instances_to_create)
        CustomFieldInstance.objects.bulk_update(
            custom_field_instances_to_update,
            ["value_document_ids"],
        )
        Document.objects.filter(id__in=target_doc_ids).update(modified=timezone.now())

    @staticmethod
    def remove_doclink(
        document: Document,
        field: CustomField,
        target_doc_id: int,
    ):
        """
        Removes a 'symmetrical' link to `document` from the target document's existing custom field instance
        """
        target_doc_field_instance = CustomFieldInstance.objects.filter(
            document_id=target_doc_id,
            field=field,
        ).first()
        if (
            target_doc_field_instance is not None
            and document.id in target_doc_field_instance.value
        ):
            target_doc_field_instance.value.remove(document.id)
            target_doc_field_instance.save()
        Document.objects.filter(id=target_doc_id).update(modified=timezone.now())

    class Meta:
        model = CustomFieldInstance
        fields = [
            "value",
            "field",
        ]


class DocumentSerializer(
    OwnedObjectSerializer,
    NestedUpdateMixin,
    DynamicFieldsModelSerializer,
):
    archive_serial_number_prefix = ArchiveSerialNumberPrefixField(allow_null=True)
    correspondent = CorrespondentField(allow_null=True)
    tags = TagsField(many=True)
    document_type = DocumentTypeField(allow_null=True)
    storage_path = StoragePathField(allow_null=True)

    original_file_name = SerializerMethodField()
    archived_file_name = SerializerMethodField()
    created_date = serializers.DateField(required=False)
    page_count = SerializerMethodField()

    custom_fields = CustomFieldInstanceSerializer(
        many=True,
        allow_null=False,
        required=False,
    )

    owner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )

    remove_inbox_tags = serializers.BooleanField(
        default=False,
        write_only=True,
        allow_null=True,
        required=False,
    )

    def get_page_count(self, obj):
        return obj.page_count

    def get_original_file_name(self, obj):
        return obj.original_filename

    def get_archived_file_name(self, obj):
        if obj.has_archive_version:
            return obj.get_public_filename(archive=True)
        else:
            return None

    def to_representation(self, instance):
        doc = super().to_representation(instance)
        if self.truncate_content and "content" in self.fields:
            doc["content"] = doc.get("content")[0:550]
        return doc

    def validate(self, attrs):
        if (
            "archive_serial_number" in attrs
            and attrs["archive_serial_number"] is not None
            and len(str(attrs["archive_serial_number"])) > 0
            and Document.deleted_objects.filter(
                archive_serial_number=attrs["archive_serial_number"],
                #archive_serial_number_prefix__prefix=attrs["archive_serial_number_prefix"], # TODO: asn type empty is allowed
            ).exists()
        ):
            raise serializers.ValidationError(
                {
                    "archive_serial_number": [
                        "Document with this Archive Serial Number already exists in the trash.",
                    ],
                },
            )
        return super().validate(attrs)

    def update(self, instance: Document, validated_data):
        if "created_date" in validated_data and "created" not in validated_data:
            new_datetime = datetime.datetime.combine(
                validated_data.get("created_date"),
                datetime.time(0, 0, 0, 0, zoneinfo.ZoneInfo(settings.TIME_ZONE)),
            )
            instance.created = new_datetime
            instance.save()
        if "created_date" in validated_data:
            validated_data.pop("created_date")
        if instance.custom_fields.count() > 0 and "custom_fields" in validated_data:
            incoming_custom_fields = [
                field["field"] for field in validated_data["custom_fields"]
            ]
            for custom_field_instance in instance.custom_fields.filter(
                field__data_type=CustomField.FieldDataType.DOCUMENTLINK,
            ):
                if (
                    custom_field_instance.field not in incoming_custom_fields
                    and custom_field_instance.value is not None
                ):
                    # Doc link field is being removed entirely
                    for doc_id in custom_field_instance.value:
                        CustomFieldInstanceSerializer.remove_doclink(
                            instance,
                            custom_field_instance.field,
                            doc_id,
                        )
        if validated_data.get("remove_inbox_tags"):
            tag_ids_being_added = (
                [
                    tag.id
                    for tag in validated_data["tags"]
                    if tag not in instance.tags.all()
                ]
                if "tags" in validated_data
                else []
            )
            inbox_tags_not_being_added = Tag.objects.filter(is_inbox_tag=True).exclude(
                id__in=tag_ids_being_added,
            )
            if "tags" in validated_data:
                validated_data["tags"] = [
                    tag
                    for tag in validated_data["tags"]
                    if tag not in inbox_tags_not_being_added
                ]
            else:
                validated_data["tags"] = [
                    tag
                    for tag in instance.tags.all()
                    if tag not in inbox_tags_not_being_added
                ]
        if settings.AUDIT_LOG_ENABLED:
            with set_actor(self.user):
                super().update(instance, validated_data)
        else:
            super().update(instance, validated_data)
        # hard delete custom field instances that were soft deleted
        CustomFieldInstance.deleted_objects.filter(document=instance).delete()
        return instance

    def __init__(self, *args, **kwargs):
        self.truncate_content = kwargs.pop("truncate_content", False)

        # return full permissions if we're doing a PATCH or PUT
        context = kwargs.get("context")
        if (
            context.get("request").method == "PATCH"
            or context.get("request").method == "PUT"
        ):
            kwargs["full_perms"] = True

        super().__init__(*args, **kwargs)

    class Meta:
        model = Document
        depth = 1
        fields = (
            "id",
            "correspondent",
            "document_type",
            "storage_path",
            "title",
            "content",
            "tags",
            "created",
            "created_date",
            "modified",
            "added",
            "deleted_at",
            "archive_serial_number_prefix",
            "archive_serial_number",
            "original_file_name",
            "archived_file_name",
            "owner",
            "permissions",
            "user_can_change",
            "is_shared_by_requester",
            "set_permissions",
            "notes",
            "custom_fields",
            "remove_inbox_tags",
            "page_count",
            "mime_type",
        )
        list_serializer_class = OwnedObjectListSerializer


class SearchResultListSerializer(serializers.ListSerializer):
    def to_representation(self, hits):
        document_ids = [hit["id"] for hit in hits]
        # Fetch all Document objects in the list in one SQL query.
        documents = self.child.fetch_documents(document_ids)
        self.child.context["documents"] = documents
        # Also check if they are shared with other users / groups.
        self.child.context["shared_object_pks"] = self.child.get_shared_object_pks(
            documents.values(),
        )

        return super().to_representation(hits)


class SearchResultSerializer(DocumentSerializer):
    @staticmethod
    def fetch_documents(ids):
        """
        Return a dict that maps given document IDs to Document objects.
        """
        return {
            document.id: document
            for document in Document.objects.select_related(
                "correspondent",
                "storage_path",
                "document_type",
                "owner",
            )
            .prefetch_related("tags", "custom_fields", "notes")
            .filter(id__in=ids)
        }

    def to_representation(self, hit):
        # Again we first check if the parent has already fetched the documents.
        documents = self.context.get("documents")
        # Otherwise we fetch this document.
        if documents is None:  # pragma: no cover
            # In practice we only serialize **lists** of whoosh.searching.Hit.
            # I'm keeping this check for completeness but marking it no cover for now.
            documents = self.fetch_documents([hit["id"]])
        document = documents[hit["id"]]

        notes = ",".join(
            [str(c.note) for c in document.notes.all()],
        )
        r = super().to_representation(document)
        r["__search_hit__"] = {
            "score": hit.score,
            "highlights": hit.highlights("content", text=document.content),
            "note_highlights": (
                hit.highlights("notes", text=notes) if document else None
            ),
            "rank": hit.rank,
        }

        return r

    class Meta(DocumentSerializer.Meta):
        list_serializer_class = SearchResultListSerializer


class SavedViewFilterRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedViewFilterRule
        fields = ["rule_type", "value"]


class SavedViewSerializer(OwnedObjectSerializer):
    filter_rules = SavedViewFilterRuleSerializer(many=True)

    class Meta:
        model = SavedView
        fields = [
            "id",
            "name",
            "show_on_dashboard",
            "show_in_sidebar",
            "sort_field",
            "sort_reverse",
            "filter_rules",
            "page_size",
            "display_mode",
            "display_fields",
            "owner",
            "permissions",
            "user_can_change",
            "set_permissions",
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if "display_fields" in attrs and attrs["display_fields"] is not None:
            for field in attrs["display_fields"]:
                if (
                    SavedView.DisplayFields.CUSTOM_FIELD[:-2] in field
                ):  # i.e. check for 'custom_field_' prefix
                    field_id = int(re.search(r"\d+", field)[0])
                    if not CustomField.objects.filter(id=field_id).exists():
                        raise serializers.ValidationError(
                            f"Invalid field: {field}",
                        )
                elif field not in SavedView.DisplayFields.values:
                    raise serializers.ValidationError(
                        f"Invalid field: {field}",
                    )
        return attrs

    def update(self, instance, validated_data):
        if "filter_rules" in validated_data:
            rules_data = validated_data.pop("filter_rules")
        else:
            rules_data = None
        if "user" in validated_data:
            # backwards compatibility
            validated_data["owner"] = validated_data.pop("user")
        super().update(instance, validated_data)
        if rules_data is not None:
            SavedViewFilterRule.objects.filter(saved_view=instance).delete()
            for rule_data in rules_data:
                SavedViewFilterRule.objects.create(saved_view=instance, **rule_data)
        return instance

    def create(self, validated_data):
        rules_data = validated_data.pop("filter_rules")
        if "user" in validated_data:
            # backwards compatibility
            validated_data["owner"] = validated_data.pop("user")
        saved_view = SavedView.objects.create(**validated_data)
        for rule_data in rules_data:
            SavedViewFilterRule.objects.create(saved_view=saved_view, **rule_data)
        return saved_view


class DocumentListSerializer(serializers.Serializer):
    documents = serializers.ListField(
        required=True,
        label="Documents",
        write_only=True,
        child=serializers.IntegerField(),
    )

    def _validate_document_id_list(self, documents, name="documents"):
        if not isinstance(documents, list):
            raise serializers.ValidationError(f"{name} must be a list")
        if not all(isinstance(i, int) for i in documents):
            raise serializers.ValidationError(f"{name} must be a list of integers")
        count = Document.objects.filter(id__in=documents).count()
        if not count == len(documents):
            raise serializers.ValidationError(
                f"Some documents in {name} don't exist or were specified twice.",
            )

    def validate_documents(self, documents):
        self._validate_document_id_list(documents)
        return documents


class BulkEditSerializer(
    SerializerWithPerms,
    DocumentListSerializer,
    SetPermissionsMixin,
):
    method = serializers.ChoiceField(
        choices=[
            "set_correspondent",
            "set_document_type",
            "set_storage_path",
            "add_tag",
            "remove_tag",
            "modify_tags",
            "modify_custom_fields",
            "delete",
            "reprocess",
            "set_permissions",
            "rotate",
            "merge",
            "split",
            "delete_pages",
        ],
        label="Method",
        write_only=True,
    )

    parameters = serializers.DictField(allow_empty=True, default={}, write_only=True)

    def _validate_tag_id_list(self, tags, name="tags"):
        if not isinstance(tags, list):
            raise serializers.ValidationError(f"{name} must be a list")
        if not all(isinstance(i, int) for i in tags):
            raise serializers.ValidationError(f"{name} must be a list of integers")
        count = Tag.objects.filter(id__in=tags).count()
        if not count == len(tags):
            raise serializers.ValidationError(
                f"Some tags in {name} don't exist or were specified twice.",
            )

    def _validate_custom_field_id_list_or_dict(
        self,
        custom_fields,
        name="custom_fields",
    ):
        ids = custom_fields
        if isinstance(custom_fields, dict):
            try:
                ids = [int(i[0]) for i in custom_fields.items()]
            except Exception as e:
                logger.exception(f"Error validating custom fields: {e}")
                raise serializers.ValidationError(
                    f"{name} must be a list of integers or a dict of id:value pairs, see the log for details",
                )
        elif not isinstance(custom_fields, list) or not all(
            isinstance(i, int) for i in ids
        ):
            raise serializers.ValidationError(
                f"{name} must be a list of integers or a dict of id:value pairs",
            )
        count = CustomField.objects.filter(id__in=ids).count()
        if not count == len(ids):
            raise serializers.ValidationError(
                f"Some custom fields in {name} don't exist or were specified twice.",
            )

    def validate_method(self, method):
        if method == "set_correspondent":
            return bulk_edit.set_correspondent
        elif method == "set_document_type":
            return bulk_edit.set_document_type
        elif method == "set_storage_path":
            return bulk_edit.set_storage_path
        elif method == "add_tag":
            return bulk_edit.add_tag
        elif method == "remove_tag":
            return bulk_edit.remove_tag
        elif method == "modify_tags":
            return bulk_edit.modify_tags
        elif method == "modify_custom_fields":
            return bulk_edit.modify_custom_fields
        elif method == "delete":
            return bulk_edit.delete
        elif method == "redo_ocr" or method == "reprocess":
            return bulk_edit.reprocess
        elif method == "set_permissions":
            return bulk_edit.set_permissions
        elif method == "rotate":
            return bulk_edit.rotate
        elif method == "merge":
            return bulk_edit.merge
        elif method == "split":
            return bulk_edit.split
        elif method == "delete_pages":
            return bulk_edit.delete_pages
        else:
            raise serializers.ValidationError("Unsupported method.")

    def _validate_parameters_tags(self, parameters):
        if "tag" in parameters:
            tag_id = parameters["tag"]
            try:
                Tag.objects.get(id=tag_id)
            except Tag.DoesNotExist:
                raise serializers.ValidationError("Tag does not exist")
        else:
            raise serializers.ValidationError("tag not specified")

    def _validate_parameters_document_type(self, parameters):
        if "document_type" in parameters:
            document_type_id = parameters["document_type"]
            if document_type_id is None:
                # None is ok
                return
            try:
                DocumentType.objects.get(id=document_type_id)
            except DocumentType.DoesNotExist:
                raise serializers.ValidationError("Document type does not exist")
        else:
            raise serializers.ValidationError("document_type not specified")

    def _validate_parameters_correspondent(self, parameters):
        if "correspondent" in parameters:
            correspondent_id = parameters["correspondent"]
            if correspondent_id is None:
                return
            try:
                Correspondent.objects.get(id=correspondent_id)
            except Correspondent.DoesNotExist:
                raise serializers.ValidationError("Correspondent does not exist")
        else:
            raise serializers.ValidationError("correspondent not specified")

    def _validate_storage_path(self, parameters):
        if "storage_path" in parameters:
            storage_path_id = parameters["storage_path"]
            if storage_path_id is None:
                return
            try:
                StoragePath.objects.get(id=storage_path_id)
            except StoragePath.DoesNotExist:
                raise serializers.ValidationError(
                    "Storage path does not exist",
                )
        else:
            raise serializers.ValidationError("storage path not specified")

    def _validate_parameters_modify_tags(self, parameters):
        if "add_tags" in parameters:
            self._validate_tag_id_list(parameters["add_tags"], "add_tags")
        else:
            raise serializers.ValidationError("add_tags not specified")

        if "remove_tags" in parameters:
            self._validate_tag_id_list(parameters["remove_tags"], "remove_tags")
        else:
            raise serializers.ValidationError("remove_tags not specified")

    def _validate_parameters_modify_custom_fields(self, parameters):
        if "add_custom_fields" in parameters:
            self._validate_custom_field_id_list_or_dict(
                parameters["add_custom_fields"],
                "add_custom_fields",
            )
        else:
            raise serializers.ValidationError("add_custom_fields not specified")

        if "remove_custom_fields" in parameters:
            self._validate_custom_field_id_list_or_dict(
                parameters["remove_custom_fields"],
                "remove_custom_fields",
            )
        else:
            raise serializers.ValidationError("remove_custom_fields not specified")

    def _validate_owner(self, owner):
        ownerUser = User.objects.get(pk=owner)
        if ownerUser is None:
            raise serializers.ValidationError("Specified owner cannot be found")
        return ownerUser

    def _validate_parameters_set_permissions(self, parameters):
        parameters["set_permissions"] = self.validate_set_permissions(
            parameters["set_permissions"],
        )
        if "owner" in parameters and parameters["owner"] is not None:
            self._validate_owner(parameters["owner"])
        if "merge" not in parameters:
            parameters["merge"] = False

    def _validate_parameters_rotate(self, parameters):
        try:
            if (
                "degrees" not in parameters
                or not float(parameters["degrees"]).is_integer()
            ):
                raise serializers.ValidationError("invalid rotation degrees")
        except ValueError:
            raise serializers.ValidationError("invalid rotation degrees")

    def _validate_parameters_split(self, parameters):
        if "pages" not in parameters:
            raise serializers.ValidationError("pages not specified")
        try:
            pages = []
            docs = parameters["pages"].split(",")
            for doc in docs:
                if "-" in doc:
                    pages.append(
                        [
                            x
                            for x in range(
                                int(doc.split("-")[0]),
                                int(doc.split("-")[1]) + 1,
                            )
                        ],
                    )
                else:
                    pages.append([int(doc)])
            parameters["pages"] = pages
        except ValueError:
            raise serializers.ValidationError("invalid pages specified")

        if "delete_originals" in parameters:
            if not isinstance(parameters["delete_originals"], bool):
                raise serializers.ValidationError("delete_originals must be a boolean")
        else:
            parameters["delete_originals"] = False

    def _validate_parameters_delete_pages(self, parameters):
        if "pages" not in parameters:
            raise serializers.ValidationError("pages not specified")
        if not isinstance(parameters["pages"], list):
            raise serializers.ValidationError("pages must be a list")
        if not all(isinstance(i, int) for i in parameters["pages"]):
            raise serializers.ValidationError("pages must be a list of integers")

    def _validate_parameters_merge(self, parameters):
        if "delete_originals" in parameters:
            if not isinstance(parameters["delete_originals"], bool):
                raise serializers.ValidationError("delete_originals must be a boolean")
        else:
            parameters["delete_originals"] = False

    def validate(self, attrs):
        method = attrs["method"]
        parameters = attrs["parameters"]

        if method == bulk_edit.set_correspondent:
            self._validate_parameters_correspondent(parameters)
        elif method == bulk_edit.set_document_type:
            self._validate_parameters_document_type(parameters)
        elif method == bulk_edit.add_tag or method == bulk_edit.remove_tag:
            self._validate_parameters_tags(parameters)
        elif method == bulk_edit.modify_tags:
            self._validate_parameters_modify_tags(parameters)
        elif method == bulk_edit.set_storage_path:
            self._validate_storage_path(parameters)
        elif method == bulk_edit.modify_custom_fields:
            self._validate_parameters_modify_custom_fields(parameters)
        elif method == bulk_edit.set_permissions:
            self._validate_parameters_set_permissions(parameters)
        elif method == bulk_edit.rotate:
            self._validate_parameters_rotate(parameters)
        elif method == bulk_edit.split:
            if len(attrs["documents"]) > 1:
                raise serializers.ValidationError(
                    "Split method only supports one document",
                )
            self._validate_parameters_split(parameters)
        elif method == bulk_edit.delete_pages:
            if len(attrs["documents"]) > 1:
                raise serializers.ValidationError(
                    "Delete pages method only supports one document",
                )
            self._validate_parameters_delete_pages(parameters)
        elif method == bulk_edit.merge:
            self._validate_parameters_merge(parameters)

        return attrs


class PostDocumentSerializer(serializers.Serializer):
    created = serializers.DateTimeField(
        label="Created",
        allow_null=True,
        write_only=True,
        required=False,
    )

    document = serializers.FileField(
        label="Document",
        write_only=True,
    )

    title = serializers.CharField(
        label="Title",
        write_only=True,
        required=False,
    )

    correspondent = serializers.PrimaryKeyRelatedField(
        queryset=Correspondent.objects.all(),
        label="Correspondent",
        allow_null=True,
        write_only=True,
        required=False,
    )

    document_type = serializers.PrimaryKeyRelatedField(
        queryset=DocumentType.objects.all(),
        label="Document type",
        allow_null=True,
        write_only=True,
        required=False,
    )

    storage_path = serializers.PrimaryKeyRelatedField(
        queryset=StoragePath.objects.all(),
        label="Storage path",
        allow_null=True,
        write_only=True,
        required=False,
    )

    tags = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Tag.objects.all(),
        label="Tags",
        write_only=True,
        required=False,
    )

    archive_serial_number = serializers.IntegerField(
        label="ASN",
        write_only=True,
        required=False,
        min_value=Document.ARCHIVE_SERIAL_NUMBER_MIN,
        max_value=Document.ARCHIVE_SERIAL_NUMBER_MAX,
    )

    custom_fields = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=CustomField.objects.all(),
        label="Custom fields",
        write_only=True,
        required=False,
    )

    def validate_document(self, document):
        document_data = document.file.read()
        mime_type = magic.from_buffer(document_data, mime=True)

        if not is_mime_type_supported(mime_type):
            if (
                mime_type in settings.CONSUMER_PDF_RECOVERABLE_MIME_TYPES
                and document.name.endswith(
                    ".pdf",
                )
            ):
                # If the file is an invalid PDF, we can try to recover it later in the consumer
                mime_type = "application/pdf"
            else:
                raise serializers.ValidationError(
                    _("File type %(type)s not supported") % {"type": mime_type},
                )

        return document.name, document_data

    def validate_correspondent(self, correspondent):
        if correspondent:
            return correspondent.id
        else:
            return None

    def validate_document_type(self, document_type):
        if document_type:
            return document_type.id
        else:
            return None

    def validate_storage_path(self, storage_path):
        if storage_path:
            return storage_path.id
        else:
            return None

    def validate_tags(self, tags):
        if tags:
            return [tag.id for tag in tags]
        else:
            return None

    def validate_custom_fields(self, custom_fields):
        if custom_fields:
            return [custom_field.id for custom_field in custom_fields]
        else:
            return None


class BulkDownloadSerializer(DocumentListSerializer):
    content = serializers.ChoiceField(
        choices=["archive", "originals", "both"],
        default="archive",
    )

    compression = serializers.ChoiceField(
        choices=["none", "deflated", "bzip2", "lzma"],
        default="none",
    )

    follow_formatting = serializers.BooleanField(
        default=False,
    )

    def validate_compression(self, compression):
        import zipfile

        return {
            "none": zipfile.ZIP_STORED,
            "deflated": zipfile.ZIP_DEFLATED,
            "bzip2": zipfile.ZIP_BZIP2,
            "lzma": zipfile.ZIP_LZMA,
        }[compression]


class StoragePathSerializer(MatchingModelSerializer, OwnedObjectSerializer):
    class Meta:
        model = StoragePath
        fields = (
            "id",
            "slug",
            "name",
            "path",
            "match",
            "matching_algorithm",
            "is_insensitive",
            "document_count",
            "owner",
            "permissions",
            "user_can_change",
            "set_permissions",
        )

    def validate_path(self, path: str):
        converted_path = convert_format_str_to_template_format(path)
        if converted_path != path:
            logger.warning(
                f"Storage path {path} is not using the new style format, consider updating",
            )
        result = validate_filepath_template_and_render(converted_path)

        if result is None:
            raise serializers.ValidationError(_("Invalid variable detected."))

        return converted_path

    def update(self, instance, validated_data):
        """
        When a storage path is updated, see if documents
        using it require a rename/move
        """
        doc_ids = [doc.id for doc in instance.documents.all()]
        if len(doc_ids):
            bulk_edit.bulk_update_documents.delay(doc_ids)

        return super().update(instance, validated_data)


class UiSettingsViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = UiSettings
        depth = 1
        fields = [
            "id",
            "settings",
        ]

    def validate_settings(self, settings):
        # we never save update checking backend setting
        if "update_checking" in settings:
            try:
                settings["update_checking"].pop("backend_setting")
            except KeyError:
                pass
        return settings

    def create(self, validated_data):
        ui_settings = UiSettings.objects.update_or_create(
            user=validated_data.get("user"),
            defaults={"settings": validated_data.get("settings", None)},
        )
        return ui_settings


class TasksViewSerializer(OwnedObjectSerializer):
    class Meta:
        model = PaperlessTask
        depth = 1
        fields = (
            "id",
            "task_id",
            "task_file_name",
            "date_created",
            "date_done",
            "type",
            "status",
            "result",
            "acknowledged",
            "related_document",
            "owner",
        )

    type = serializers.SerializerMethodField()

    def get_type(self, obj):
        # just file tasks, for now
        return "file"

    related_document = serializers.SerializerMethodField()
    created_doc_re = re.compile(r"New document id (\d+) created")
    duplicate_doc_re = re.compile(r"It is a duplicate of .* \(#(\d+)\)")

    def get_related_document(self, obj):
        result = None
        re = None
        match obj.status:
            case states.SUCCESS:
                re = self.created_doc_re
            case states.FAILURE:
                re = (
                    self.duplicate_doc_re
                    if "existing document is in the trash" not in obj.result
                    else None
                )
        if re is not None:
            try:
                result = re.search(obj.result).group(1)
            except Exception:
                pass

        return result


class AcknowledgeTasksViewSerializer(serializers.Serializer):
    tasks = serializers.ListField(
        required=True,
        label="Tasks",
        write_only=True,
        child=serializers.IntegerField(),
    )

    def _validate_task_id_list(self, tasks, name="tasks"):
        if not isinstance(tasks, list):
            raise serializers.ValidationError(f"{name} must be a list")
        if not all(isinstance(i, int) for i in tasks):
            raise serializers.ValidationError(f"{name} must be a list of integers")
        count = PaperlessTask.objects.filter(id__in=tasks).count()
        if not count == len(tasks):
            raise serializers.ValidationError(
                f"Some tasks in {name} don't exist or were specified twice.",
            )

    def validate_tasks(self, tasks):
        self._validate_task_id_list(tasks)
        return tasks


class ShareLinkSerializer(OwnedObjectSerializer):
    class Meta:
        model = ShareLink
        fields = (
            "id",
            "created",
            "expiration",
            "slug",
            "document",
            "file_version",
        )

    def create(self, validated_data):
        validated_data["slug"] = get_random_string(50)
        return super().create(validated_data)


class BulkEditObjectsSerializer(SerializerWithPerms, SetPermissionsMixin):
    objects = serializers.ListField(
        required=True,
        allow_empty=False,
        label="Objects",
        write_only=True,
        child=serializers.IntegerField(),
    )

    object_type = serializers.ChoiceField(
        choices=[
            "tags",
            "correspondents",
            "document_types",
            "storage_paths",
        ],
        label="Object Type",
        write_only=True,
    )

    operation = serializers.ChoiceField(
        choices=[
            "set_permissions",
            "delete",
        ],
        label="Operation",
        required=True,
        write_only=True,
    )

    owner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )

    permissions = serializers.DictField(
        label="Set permissions",
        allow_empty=False,
        required=False,
        write_only=True,
    )

    merge = serializers.BooleanField(
        default=False,
        write_only=True,
        required=False,
    )

    def get_object_class(self, object_type):
        object_class = None
        if object_type == "tags":
            object_class = Tag
        elif object_type == "correspondents":
            object_class = Correspondent
        elif object_type == "document_types":
            object_class = DocumentType
        elif object_type == "storage_paths":
            object_class = StoragePath
        return object_class

    def _validate_objects(self, objects, object_type):
        if not isinstance(objects, list):
            raise serializers.ValidationError("objects must be a list")
        if not all(isinstance(i, int) for i in objects):
            raise serializers.ValidationError("objects must be a list of integers")
        object_class = self.get_object_class(object_type)
        count = object_class.objects.filter(id__in=objects).count()
        if not count == len(objects):
            raise serializers.ValidationError(
                "Some ids in objects don't exist or were specified twice.",
            )
        return objects

    def _validate_permissions(self, permissions):
        self.validate_set_permissions(
            permissions,
        )

    def validate(self, attrs):
        object_type = attrs["object_type"]
        objects = attrs["objects"]
        operation = attrs.get("operation")

        self._validate_objects(objects, object_type)

        if operation == "set_permissions":
            permissions = attrs.get("permissions")
            if permissions is not None:
                self._validate_permissions(permissions)

        return attrs


class WorkflowTriggerSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    sources = fields.MultipleChoiceField(
        choices=WorkflowTrigger.DocumentSourceChoices.choices,
        allow_empty=True,
        default={
            DocumentSource.ConsumeFolder,
            DocumentSource.ApiUpload,
            DocumentSource.MailFetch,
        },
    )

    type = serializers.ChoiceField(
        choices=WorkflowTrigger.WorkflowTriggerType.choices,
        label="Trigger Type",
    )

    class Meta:
        model = WorkflowTrigger
        fields = [
            "id",
            "sources",
            "type",
            "filter_path",
            "filter_filename",
            "filter_mailrule",
            "matching_algorithm",
            "match",
            "is_insensitive",
            "filter_has_tags",
            "filter_has_correspondent",
            "filter_has_document_type",
            "schedule_offset_days",
            "schedule_is_recurring",
            "schedule_recurring_interval_days",
            "schedule_date_field",
            "schedule_date_custom_field",
        ]

    def validate(self, attrs):
        # Empty strings treated as None to avoid unexpected behavior
        if (
            "filter_filename" in attrs
            and attrs["filter_filename"] is not None
            and len(attrs["filter_filename"]) == 0
        ):
            attrs["filter_filename"] = None
        if (
            "filter_path" in attrs
            and attrs["filter_path"] is not None
            and len(attrs["filter_path"]) == 0
        ):
            attrs["filter_path"] = None

        if (
            attrs["type"] == WorkflowTrigger.WorkflowTriggerType.CONSUMPTION
            and "filter_mailrule" not in attrs
            and ("filter_filename" not in attrs or attrs["filter_filename"] is None)
            and ("filter_path" not in attrs or attrs["filter_path"] is None)
        ):
            raise serializers.ValidationError(
                "File name, path or mail rule filter are required",
            )

        return attrs


class WorkflowActionEmailSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(allow_null=True, required=False)

    class Meta:
        model = WorkflowActionEmail
        fields = [
            "id",
            "subject",
            "body",
            "to",
            "include_document",
        ]


class WorkflowActionWebhookSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(allow_null=True, required=False)

    class Meta:
        model = WorkflowActionWebhook
        fields = [
            "id",
            "url",
            "use_params",
            "as_json",
            "params",
            "body",
            "headers",
            "include_document",
        ]


class WorkflowActionSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    assign_correspondent = CorrespondentField(allow_null=True, required=False)
    assign_tags = TagsField(many=True, allow_null=True, required=False)
    assign_document_type = DocumentTypeField(allow_null=True, required=False)
    assign_storage_path = StoragePathField(allow_null=True, required=False)
    email = WorkflowActionEmailSerializer(allow_null=True, required=False)
    webhook = WorkflowActionWebhookSerializer(allow_null=True, required=False)

    class Meta:
        model = WorkflowAction
        fields = [
            "id",
            "type",
            "assign_title",
            "assign_tags",
            "assign_correspondent",
            "assign_document_type",
            "assign_storage_path",
            "assign_owner",
            "assign_view_users",
            "assign_view_groups",
            "assign_change_users",
            "assign_change_groups",
            "assign_custom_fields",
            "remove_all_tags",
            "remove_tags",
            "remove_all_correspondents",
            "remove_correspondents",
            "remove_all_document_types",
            "remove_document_types",
            "remove_all_storage_paths",
            "remove_storage_paths",
            "remove_custom_fields",
            "remove_all_custom_fields",
            "remove_all_owners",
            "remove_owners",
            "remove_all_permissions",
            "remove_view_users",
            "remove_view_groups",
            "remove_change_users",
            "remove_change_groups",
            "email",
            "webhook",
        ]

    def validate(self, attrs):
        if "assign_title" in attrs and attrs["assign_title"] is not None:
            if len(attrs["assign_title"]) == 0:
                # Empty strings treated as None to avoid unexpected behavior
                attrs["assign_title"] = None
            else:
                try:
                    # test against all placeholders, see consumer.py `parse_doc_title_w_placeholders`
                    attrs["assign_title"].format(
                        correspondent="",
                        document_type="",
                        added="",
                        added_year="",
                        added_year_short="",
                        added_month="",
                        added_month_name="",
                        added_month_name_short="",
                        added_day="",
                        added_time="",
                        owner_username="",
                        original_filename="",
                        filename="",
                        created="",
                        created_year="",
                        created_year_short="",
                        created_month="",
                        created_month_name="",
                        created_month_name_short="",
                        created_day="",
                        created_time="",
                    )
                except (ValueError, KeyError) as e:
                    raise serializers.ValidationError(
                        {"assign_title": f'Invalid f-string detected: "{e.args[0]}"'},
                    )

        if (
            "type" in attrs
            and attrs["type"] == WorkflowAction.WorkflowActionType.EMAIL
            and "email" not in attrs
        ):
            raise serializers.ValidationError(
                "Email data is required for email actions",
            )

        if (
            "type" in attrs
            and attrs["type"] == WorkflowAction.WorkflowActionType.WEBHOOK
            and "webhook" not in attrs
        ):
            raise serializers.ValidationError(
                "Webhook data is required for webhook actions",
            )

        return attrs


class WorkflowSerializer(serializers.ModelSerializer):
    order = serializers.IntegerField(required=False)

    triggers = WorkflowTriggerSerializer(many=True)
    actions = WorkflowActionSerializer(many=True)

    class Meta:
        model = Workflow
        fields = [
            "id",
            "name",
            "order",
            "enabled",
            "triggers",
            "actions",
        ]

    def update_triggers_and_actions(self, instance: Workflow, triggers, actions):
        set_triggers = []
        set_actions = []

        if triggers is not None:
            for trigger in triggers:
                filter_has_tags = trigger.pop("filter_has_tags", None)
                trigger_instance, _ = WorkflowTrigger.objects.update_or_create(
                    id=trigger.get("id"),
                    defaults=trigger,
                )
                if filter_has_tags is not None:
                    trigger_instance.filter_has_tags.set(filter_has_tags)
                set_triggers.append(trigger_instance)

        if actions is not None:
            for action in actions:
                assign_tags = action.pop("assign_tags", None)
                assign_view_users = action.pop("assign_view_users", None)
                assign_view_groups = action.pop("assign_view_groups", None)
                assign_change_users = action.pop("assign_change_users", None)
                assign_change_groups = action.pop("assign_change_groups", None)
                assign_custom_fields = action.pop("assign_custom_fields", None)
                remove_tags = action.pop("remove_tags", None)
                remove_correspondents = action.pop("remove_correspondents", None)
                remove_document_types = action.pop("remove_document_types", None)
                remove_storage_paths = action.pop("remove_storage_paths", None)
                remove_custom_fields = action.pop("remove_custom_fields", None)
                remove_owners = action.pop("remove_owners", None)
                remove_view_users = action.pop("remove_view_users", None)
                remove_view_groups = action.pop("remove_view_groups", None)
                remove_change_users = action.pop("remove_change_users", None)
                remove_change_groups = action.pop("remove_change_groups", None)

                email_data = action.pop("email", None)
                webhook_data = action.pop("webhook", None)

                action_instance, _ = WorkflowAction.objects.update_or_create(
                    id=action.get("id"),
                    defaults=action,
                )

                if email_data is not None:
                    serializer = WorkflowActionEmailSerializer(data=email_data)
                    serializer.is_valid(raise_exception=True)
                    email, _ = WorkflowActionEmail.objects.update_or_create(
                        id=email_data.get("id"),
                        defaults=serializer.validated_data,
                    )
                    action_instance.email = email
                    action_instance.save()

                if webhook_data is not None:
                    serializer = WorkflowActionWebhookSerializer(data=webhook_data)
                    serializer.is_valid(raise_exception=True)
                    webhook, _ = WorkflowActionWebhook.objects.update_or_create(
                        id=webhook_data.get("id"),
                        defaults=serializer.validated_data,
                    )
                    action_instance.webhook = webhook
                    action_instance.save()

                if assign_tags is not None:
                    action_instance.assign_tags.set(assign_tags)
                if assign_view_users is not None:
                    action_instance.assign_view_users.set(assign_view_users)
                if assign_view_groups is not None:
                    action_instance.assign_view_groups.set(assign_view_groups)
                if assign_change_users is not None:
                    action_instance.assign_change_users.set(assign_change_users)
                if assign_change_groups is not None:
                    action_instance.assign_change_groups.set(assign_change_groups)
                if assign_custom_fields is not None:
                    action_instance.assign_custom_fields.set(assign_custom_fields)
                if remove_tags is not None:
                    action_instance.remove_tags.set(remove_tags)
                if remove_correspondents is not None:
                    action_instance.remove_correspondents.set(remove_correspondents)
                if remove_document_types is not None:
                    action_instance.remove_document_types.set(remove_document_types)
                if remove_storage_paths is not None:
                    action_instance.remove_storage_paths.set(remove_storage_paths)
                if remove_custom_fields is not None:
                    action_instance.remove_custom_fields.set(remove_custom_fields)
                if remove_owners is not None:
                    action_instance.remove_owners.set(remove_owners)
                if remove_view_users is not None:
                    action_instance.remove_view_users.set(remove_view_users)
                if remove_view_groups is not None:
                    action_instance.remove_view_groups.set(remove_view_groups)
                if remove_change_users is not None:
                    action_instance.remove_change_users.set(remove_change_users)
                if remove_change_groups is not None:
                    action_instance.remove_change_groups.set(remove_change_groups)

                set_actions.append(action_instance)

        instance.triggers.set(set_triggers)
        instance.actions.set(set_actions)
        instance.save()

    def prune_triggers_and_actions(self):
        """
        ManyToMany fields dont support e.g. on_delete so we need to discard unattached
        triggers and actionas manually
        """
        for trigger in WorkflowTrigger.objects.all():
            if trigger.workflows.all().count() == 0:
                trigger.delete()

        for action in WorkflowAction.objects.all():
            if action.workflows.all().count() == 0:
                action.delete()

        WorkflowActionEmail.objects.filter(action=None).delete()
        WorkflowActionWebhook.objects.filter(action=None).delete()

    def create(self, validated_data) -> Workflow:
        if "triggers" in validated_data:
            triggers = validated_data.pop("triggers")

        if "actions" in validated_data:
            actions = validated_data.pop("actions")

        instance = super().create(validated_data)

        self.update_triggers_and_actions(instance, triggers, actions)

        return instance

    def update(self, instance: Workflow, validated_data) -> Workflow:
        if "triggers" in validated_data:
            triggers = validated_data.pop("triggers")

        if "actions" in validated_data:
            actions = validated_data.pop("actions")

        instance = super().update(instance, validated_data)

        self.update_triggers_and_actions(instance, triggers, actions)

        self.prune_triggers_and_actions()

        return instance


class TrashSerializer(SerializerWithPerms):
    documents = serializers.ListField(
        required=False,
        label="Documents",
        write_only=True,
        child=serializers.IntegerField(),
    )

    action = serializers.ChoiceField(
        choices=["restore", "empty"],
        label="Action",
        write_only=True,
    )

    def validate_documents(self, documents):
        count = Document.deleted_objects.filter(id__in=documents).count()
        if not count == len(documents):
            raise serializers.ValidationError(
                "Some documents in the list have not yet been deleted.",
            )
        return documents


class StoragePathTestSerializer(SerializerWithPerms):
    path = serializers.CharField(
        required=True,
        label="Path",
        write_only=True,
    )

    document = serializers.PrimaryKeyRelatedField(
        queryset=Document.objects.all(),
        required=True,
        label="Document",
        write_only=True,
    )
