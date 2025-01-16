import functools
import inspect
import json
import operator
from collections.abc import Callable
from contextlib import contextmanager

from django.contrib.contenttypes.models import ContentType
from django.db.models import Case
from django.db.models import CharField
from django.db.models import Count
from django.db.models import Exists
from django.db.models import IntegerField
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Sum
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Cast
from django.utils.translation import gettext_lazy as _
from django_filters.rest_framework import BooleanFilter
from django_filters.rest_framework import Filter
from django_filters.rest_framework import FilterSet
from guardian.utils import get_group_obj_perms_model
from guardian.utils import get_user_obj_perms_model
from rest_framework import serializers
from rest_framework.filters import OrderingFilter
from rest_framework_guardian.filters import ObjectPermissionsFilter

from documents.models import ArchiveSerialNumberPrefix
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import Log
from documents.models import ShareLink
from documents.models import StoragePath
from documents.models import Tag

CHAR_KWARGS = ["istartswith", "iendswith", "icontains", "iexact"]
ID_KWARGS = ["in", "exact"]
INT_KWARGS = ["exact", "gt", "gte", "lt", "lte", "isnull"]
DATE_KWARGS = ["year", "month", "day", "date__gt", "gt", "date__lt", "lt"]

CUSTOM_FIELD_QUERY_MAX_DEPTH = 10
CUSTOM_FIELD_QUERY_MAX_ATOMS = 20


class CorrespondentFilterSet(FilterSet):
    class Meta:
        model = Correspondent
        fields = {
            "id": ID_KWARGS,
            "name": CHAR_KWARGS,
        }


class TagFilterSet(FilterSet):
    class Meta:
        model = Tag
        fields = {
            "id": ID_KWARGS,
            "name": CHAR_KWARGS,
        }


class ArchiveSerialNumberPrefixFilterSet(FilterSet):
    class Meta:
        model = ArchiveSerialNumberPrefix
        fields = {
            "id": ID_KWARGS,
            "name": CHAR_KWARGS,
        }

class DocumentTypeFilterSet(FilterSet):
    class Meta:
        model = DocumentType
        fields = {
            "id": ID_KWARGS,
            "name": CHAR_KWARGS,
        }


class StoragePathFilterSet(FilterSet):
    class Meta:
        model = StoragePath
        fields = {
            "id": ID_KWARGS,
            "name": CHAR_KWARGS,
            "path": CHAR_KWARGS,
        }


class ObjectFilter(Filter):
    def __init__(self, exclude=False, in_list=False, field_name=""):
        super().__init__()
        self.exclude = exclude
        self.in_list = in_list
        self.field_name = field_name

    def filter(self, qs, value):
        if not value:
            return qs

        try:
            object_ids = [int(x) for x in value.split(",")]
        except ValueError:
            return qs

        if self.in_list:
            qs = qs.filter(**{f"{self.field_name}__id__in": object_ids}).distinct()
        else:
            for obj_id in object_ids:
                if self.exclude:
                    qs = qs.exclude(**{f"{self.field_name}__id": obj_id})
                else:
                    qs = qs.filter(**{f"{self.field_name}__id": obj_id})

        return qs


class InboxFilter(Filter):
    def filter(self, qs, value):
        if value == "true":
            return qs.filter(tags__is_inbox_tag=True)
        elif value == "false":
            return qs.exclude(tags__is_inbox_tag=True)
        else:
            return qs


class TitleContentFilter(Filter):
    def filter(self, qs, value):
        if value:
            return qs.filter(Q(title__icontains=value) | Q(content__icontains=value))
        else:
            return qs


class SharedByUser(Filter):
    def filter(self, qs, value):
        ctype = ContentType.objects.get_for_model(self.model)
        UserObjectPermission = get_user_obj_perms_model()
        GroupObjectPermission = get_group_obj_perms_model()
        # see https://github.com/paperless-ngx/paperless-ngx/issues/5392, we limit subqueries
        # to 1 because Postgres doesn't like returning > 1 row, but all we care about is > 0
        return (
            qs.filter(
                owner_id=value,
            )
            .annotate(
                num_shared_users=Count(
                    UserObjectPermission.objects.filter(
                        content_type=ctype,
                        object_pk=Cast(OuterRef("pk"), CharField()),
                    ).values("user_id")[:1],
                ),
            )
            .annotate(
                num_shared_groups=Count(
                    GroupObjectPermission.objects.filter(
                        content_type=ctype,
                        object_pk=Cast(OuterRef("pk"), CharField()),
                    ).values("group_id")[:1],
                ),
            )
            .filter(
                Q(num_shared_users__gt=0) | Q(num_shared_groups__gt=0),
            )
            if value is not None
            else qs
        )


class CustomFieldFilterSet(FilterSet):
    class Meta:
        model = CustomField
        fields = {
            "id": ID_KWARGS,
            "name": CHAR_KWARGS,
        }


class CustomFieldsFilter(Filter):
    def filter(self, qs, value):
        if value:
            fields_with_matching_selects = CustomField.objects.filter(
                extra_data__icontains=value,
            )
            option_ids = []
            if fields_with_matching_selects.count() > 0:
                for field in fields_with_matching_selects:
                    options = field.extra_data.get("select_options", [])
                    for _, option in enumerate(options):
                        if option.get("label").lower().find(value.lower()) != -1:
                            option_ids.extend([option.get("id")])
            return (
                qs.filter(custom_fields__field__name__icontains=value)
                | qs.filter(custom_fields__value_text__icontains=value)
                | qs.filter(custom_fields__value_bool__icontains=value)
                | qs.filter(custom_fields__value_int__icontains=value)
                | qs.filter(custom_fields__value_float__icontains=value)
                | qs.filter(custom_fields__value_date__icontains=value)
                | qs.filter(custom_fields__value_url__icontains=value)
                | qs.filter(custom_fields__value_monetary__icontains=value)
                | qs.filter(custom_fields__value_document_ids__icontains=value)
                | qs.filter(custom_fields__value_select__in=option_ids)
            )
        else:
            return qs


class SelectField(serializers.CharField):
    def __init__(self, custom_field: CustomField):
        self._options = custom_field.extra_data["select_options"]
        super().__init__(max_length=16)

    def to_internal_value(self, data):
        # If the supplied value is the option label instead of the ID
        try:
            data = next(
                option.get("id")
                for option in self._options
                if option.get("label") == data
            )
        except StopIteration:
            pass
        return super().to_internal_value(data)


def handle_validation_prefix(func: Callable):
    """
    Catch ValidationErrors raised by the wrapped function
    and add a prefix to the exception detail to track what causes the exception,
    similar to nested serializers.
    """

    def wrapper(*args, validation_prefix=None, **kwargs):
        try:
            return func(*args, **kwargs)
        except serializers.ValidationError as e:
            raise serializers.ValidationError({validation_prefix: e.detail})

    # Update the signature to include the validation_prefix argument
    old_sig = inspect.signature(func)
    new_param = inspect.Parameter("validation_prefix", inspect.Parameter.KEYWORD_ONLY)
    new_sig = old_sig.replace(parameters=[*old_sig.parameters.values(), new_param])

    # Apply functools.wraps and manually set the new signature
    functools.update_wrapper(wrapper, func)
    wrapper.__signature__ = new_sig

    return wrapper


class CustomFieldQueryParser:
    EXPR_BY_CATEGORY = {
        "basic": ["exact", "in", "isnull", "exists"],
        "string": [
            "icontains",
            "istartswith",
            "iendswith",
        ],
        "arithmetic": [
            "gt",
            "gte",
            "lt",
            "lte",
            "range",
        ],
        "containment": ["contains"],
    }

    SUPPORTED_EXPR_CATEGORIES = {
        CustomField.FieldDataType.STRING: ("basic", "string"),
        CustomField.FieldDataType.URL: ("basic", "string"),
        CustomField.FieldDataType.DATE: ("basic", "arithmetic"),
        CustomField.FieldDataType.BOOL: ("basic",),
        CustomField.FieldDataType.INT: ("basic", "arithmetic"),
        CustomField.FieldDataType.FLOAT: ("basic", "arithmetic"),
        CustomField.FieldDataType.MONETARY: ("basic", "string", "arithmetic"),
        CustomField.FieldDataType.DOCUMENTLINK: ("basic", "containment"),
        CustomField.FieldDataType.SELECT: ("basic",),
    }

    DATE_COMPONENTS = [
        "year",
        "iso_year",
        "month",
        "day",
        "week",
        "week_day",
        "iso_week_day",
        "quarter",
    ]

    def __init__(
        self,
        validation_prefix,
        max_query_depth=10,
        max_atom_count=20,
    ) -> None:
        """
        A helper class that parses the query string into a `django.db.models.Q` for filtering
        documents based on custom field values.

        The syntax of the query expression is illustrated with the below pseudo code rules:
        1. parse([`custom_field`, "exists", true]):
            matches documents with Q(custom_fields__field=`custom_field`)
        2. parse([`custom_field`, "exists", false]):
            matches documents with ~Q(custom_fields__field=`custom_field`)
        3. parse([`custom_field`, `op`, `value`]):
            matches documents with
            Q(custom_fields__field=`custom_field`, custom_fields__value_`type`__`op`= `value`)
        4. parse(["AND", [`q0`, `q1`, ..., `qn`]])
            -> parse(`q0`) & parse(`q1`) & ... & parse(`qn`)
        5. parse(["OR", [`q0`, `q1`, ..., `qn`]])
            -> parse(`q0`) | parse(`q1`) | ... | parse(`qn`)
        6. parse(["NOT", `q`])
            -> ~parse(`q`)

        Args:
            validation_prefix: Used to generate the ValidationError message.
            max_query_depth: Limits the maximum nesting depth of queries.
            max_atom_count: Limits the maximum number of atoms (i.e., rule 1, 2, 3) in the query.

        `max_query_depth` and `max_atom_count` can be set to guard against generating arbitrarily
        complex SQL queries.
        """
        self._custom_fields: dict[int | str, CustomField] = {}
        self._validation_prefix = validation_prefix
        # Dummy ModelSerializer used to convert a Django models.Field to serializers.Field.
        self._model_serializer = serializers.ModelSerializer()
        # Used for sanity check
        self._max_query_depth = max_query_depth
        self._max_atom_count = max_atom_count
        self._current_depth = 0
        self._atom_count = 0
        # The set of annotations that we need to apply to the queryset
        self._annotations = {}

    def parse(self, query: str) -> tuple[Q, dict[str, Count]]:
        """
        Parses the query string into a `django.db.models.Q`
        and a set of annotations to be applied to the queryset.
        """
        try:
            expr = json.loads(query)
        except json.JSONDecodeError:
            raise serializers.ValidationError(
                {self._validation_prefix: [_("Value must be valid JSON.")]},
            )
        return (
            self._parse_expr(expr, validation_prefix=self._validation_prefix),
            self._annotations,
        )

    @handle_validation_prefix
    def _parse_expr(self, expr) -> Q:
        """
        Applies rule (1, 2, 3) or (4, 5, 6) based on the length of the expr.
        """
        with self._track_query_depth():
            if isinstance(expr, list | tuple):
                if len(expr) == 2:
                    return self._parse_logical_expr(*expr)
                elif len(expr) == 3:
                    return self._parse_atom(*expr)
            raise serializers.ValidationError(
                [_("Invalid custom field query expression")],
            )

    @handle_validation_prefix
    def _parse_expr_list(self, exprs) -> list[Q]:
        """
        Handles [`q0`, `q1`, ..., `qn`] in rule 4 & 5.
        """
        if not isinstance(exprs, list | tuple) or not exprs:
            raise serializers.ValidationError(
                [_("Invalid expression list. Must be nonempty.")],
            )
        return [
            self._parse_expr(expr, validation_prefix=i) for i, expr in enumerate(exprs)
        ]

    def _parse_logical_expr(self, op, args) -> Q:
        """
        Handles rule 4, 5, 6.
        """
        op_lower = op.lower()

        if op_lower == "not":
            return ~self._parse_expr(args, validation_prefix=1)

        if op_lower == "and":
            op_func = operator.and_
        elif op_lower == "or":
            op_func = operator.or_
        else:
            raise serializers.ValidationError(
                {"0": [_("Invalid logical operator {op!r}").format(op=op)]},
            )

        qs = self._parse_expr_list(args, validation_prefix="1")
        return functools.reduce(op_func, qs)

    def _parse_atom(self, id_or_name, op, value) -> Q:
        """
        Handles rule 1, 2, 3.
        """
        # Guard against queries with too many conditions.
        self._atom_count += 1
        if self._atom_count > self._max_atom_count:
            raise serializers.ValidationError(
                [_("Maximum number of query conditions exceeded.")],
            )

        custom_field = self._get_custom_field(id_or_name, validation_prefix="0")
        op = self._validate_atom_op(custom_field, op, validation_prefix="1")
        value = self._validate_atom_value(
            custom_field,
            op,
            value,
            validation_prefix="2",
        )

        # Needed because not all DB backends support Array __contains
        if (
            custom_field.data_type == CustomField.FieldDataType.DOCUMENTLINK
            and op == "contains"
        ):
            return self._parse_atom_doc_link_contains(custom_field, value)

        value_field_name = CustomFieldInstance.get_value_field_name(
            custom_field.data_type,
        )
        if (
            custom_field.data_type == CustomField.FieldDataType.MONETARY
            and op in self.EXPR_BY_CATEGORY["arithmetic"]
        ):
            value_field_name = "value_monetary_amount"
        has_field = Q(custom_fields__field=custom_field)

        # We need to use an annotation here because different atoms
        # might be referring to different instances of custom fields.
        annotation_name = f"_custom_field_filter_{len(self._annotations)}"

        # Our special exists operator.
        if op == "exists":
            annotation = Count("custom_fields", filter=has_field)
            # A Document should have > 0 match if it has this field, or 0 if doesn't.
            query_op = "gt" if value else "exact"
            query = Q(**{f"{annotation_name}__{query_op}": 0})
        else:
            # Check if 1) custom field name matches, and 2) value satisfies condition
            field_filter = has_field & Q(
                **{f"custom_fields__{value_field_name}__{op}": value},
            )
            # Annotate how many matching custom fields each document has
            annotation = Count("custom_fields", filter=field_filter)
            # Filter document by count
            query = Q(**{f"{annotation_name}__gt": 0})

        self._annotations[annotation_name] = annotation
        return query

    @handle_validation_prefix
    def _get_custom_field(self, id_or_name):
        """Get the CustomField instance by id or name."""
        if id_or_name in self._custom_fields:
            return self._custom_fields[id_or_name]

        kwargs = (
            {"id": id_or_name} if isinstance(id_or_name, int) else {"name": id_or_name}
        )
        try:
            custom_field = CustomField.objects.get(**kwargs)
        except CustomField.DoesNotExist:
            raise serializers.ValidationError(
                [_("{name!r} is not a valid custom field.").format(name=id_or_name)],
            )
        self._custom_fields[custom_field.id] = custom_field
        self._custom_fields[custom_field.name] = custom_field
        return custom_field

    @staticmethod
    def _split_op(full_op):
        *prefix, op = str(full_op).rsplit("__", maxsplit=1)
        prefix = prefix[0] if prefix else None
        return prefix, op

    @handle_validation_prefix
    def _validate_atom_op(self, custom_field, raw_op):
        """Check if the `op` is compatible with the type of the custom field."""
        prefix, op = self._split_op(raw_op)

        # Check if the operator is supported for the current data_type.
        supported = False
        for category in self.SUPPORTED_EXPR_CATEGORIES[custom_field.data_type]:
            if op in self.EXPR_BY_CATEGORY[category]:
                supported = True
                break

        # Check prefix
        if prefix is not None:
            if (
                prefix in self.DATE_COMPONENTS
                and custom_field.data_type == CustomField.FieldDataType.DATE
            ):
                pass  # ok - e.g., "year__exact" for date field
            else:
                supported = False  # anything else is invalid

        if not supported:
            raise serializers.ValidationError(
                [
                    _("{data_type} does not support query expr {expr!r}.").format(
                        data_type=custom_field.data_type,
                        expr=raw_op,
                    ),
                ],
            )

        return raw_op

    def _get_serializer_field(self, custom_field, full_op):
        """Return a serializers.Field for value validation."""
        prefix, op = self._split_op(full_op)
        field = None

        if op in ("isnull", "exists"):
            # `isnull` takes either True or False regardless of the data_type.
            field = serializers.BooleanField()
        elif (
            custom_field.data_type == CustomField.FieldDataType.DATE
            and prefix in self.DATE_COMPONENTS
        ):
            # DateField admits queries in the form of `year__exact`, etc. These take integers.
            field = serializers.IntegerField()
        elif custom_field.data_type == CustomField.FieldDataType.DOCUMENTLINK:
            # We can be more specific here and make sure the value is a list.
            field = serializers.ListField(child=serializers.IntegerField())
        elif custom_field.data_type == CustomField.FieldDataType.SELECT:
            # We use this custom field to permit SELECT option names.
            field = SelectField(custom_field)
        elif custom_field.data_type == CustomField.FieldDataType.URL:
            # For URL fields we don't need to be strict about validation (e.g., for istartswith).
            field = serializers.CharField()
        else:
            # The general case: inferred from the corresponding field in CustomFieldInstance.
            value_field_name = CustomFieldInstance.get_value_field_name(
                custom_field.data_type,
            )
            model_field = CustomFieldInstance._meta.get_field(value_field_name)
            field_name = model_field.deconstruct()[0]
            field_class, field_kwargs = self._model_serializer.build_standard_field(
                field_name,
                model_field,
            )
            field = field_class(**field_kwargs)
            field.allow_null = False

            # Need to set allow_blank manually because of the inconsistency in CustomFieldInstance validation.
            # See https://github.com/paperless-ngx/paperless-ngx/issues/7361.
            if isinstance(field, serializers.CharField):
                field.allow_blank = True

        if op == "in":
            # `in` takes a list of values.
            field = serializers.ListField(child=field, allow_empty=False)
        elif op == "range":
            # `range` takes a list of values, i.e., [start, end].
            field = serializers.ListField(
                child=field,
                min_length=2,
                max_length=2,
            )

        return field

    @handle_validation_prefix
    def _validate_atom_value(self, custom_field, op, value):
        """Check if `value` is valid for the custom field and `op`. Returns the validated value."""
        serializer_field = self._get_serializer_field(custom_field, op)
        return serializer_field.run_validation(value)

    def _parse_atom_doc_link_contains(self, custom_field, value) -> Q:
        """
        Handles document link `contains` in a way that is supported by all DB backends.
        """

        # If the value is an empty set,
        # this is trivially true for any document with not null document links.
        if not value:
            return Q(
                custom_fields__field=custom_field,
                custom_fields__value_document_ids__isnull=False,
            )

        # First we look up reverse links from the requested documents.
        links = CustomFieldInstance.objects.filter(
            document_id__in=value,
            field__data_type=CustomField.FieldDataType.DOCUMENTLINK,
        )

        # Check if any of the requested IDs are missing.
        missing_ids = set(value) - set(link.document_id for link in links)
        if missing_ids:
            # The result should be an empty set in this case.
            return Q(id__in=[])

        # Take the intersection of the reverse links - this should be what we are looking for.
        document_ids_we_want = functools.reduce(
            operator.and_,
            (set(link.value_document_ids) for link in links),
        )

        return Q(id__in=document_ids_we_want)

    @contextmanager
    def _track_query_depth(self):
        # guard against queries that are too deeply nested
        self._current_depth += 1
        if self._current_depth > self._max_query_depth:
            raise serializers.ValidationError([_("Maximum nesting depth exceeded.")])
        try:
            yield
        finally:
            self._current_depth -= 1


class CustomFieldQueryFilter(Filter):
    def __init__(self, validation_prefix):
        """
        A filter that filters documents based on custom field name and value.

        Args:
            validation_prefix: Used to generate the ValidationError message.
        """
        super().__init__()
        self._validation_prefix = validation_prefix

    def filter(self, qs, value):
        if not value:
            return qs

        parser = CustomFieldQueryParser(
            self._validation_prefix,
            max_query_depth=CUSTOM_FIELD_QUERY_MAX_DEPTH,
            max_atom_count=CUSTOM_FIELD_QUERY_MAX_ATOMS,
        )
        q, annotations = parser.parse(value)

        return qs.annotate(**annotations).filter(q)


class DocumentFilterSet(FilterSet):
    is_tagged = BooleanFilter(
        label="Is tagged",
        field_name="tags",
        lookup_expr="isnull",
        exclude=True,
    )

    tags__id__all = ObjectFilter(field_name="tags")

    tags__id__none = ObjectFilter(field_name="tags", exclude=True)

    tags__id__in = ObjectFilter(field_name="tags", in_list=True)

    correspondent__id__none = ObjectFilter(field_name="correspondent", exclude=True)

    document_type__id__none = ObjectFilter(field_name="document_type", exclude=True)

    storage_path__id__none = ObjectFilter(field_name="storage_path", exclude=True)

    is_in_inbox = InboxFilter()

    title_content = TitleContentFilter()

    owner__id__none = ObjectFilter(field_name="owner", exclude=True)

    custom_fields__icontains = CustomFieldsFilter()

    custom_fields__id__all = ObjectFilter(field_name="custom_fields__field")

    custom_fields__id__none = ObjectFilter(
        field_name="custom_fields__field",
        exclude=True,
    )

    custom_fields__id__in = ObjectFilter(
        field_name="custom_fields__field",
        in_list=True,
    )

    has_custom_fields = BooleanFilter(
        label="Has custom field",
        field_name="custom_fields",
        lookup_expr="isnull",
        exclude=True,
    )

    custom_field_query = CustomFieldQueryFilter("custom_field_query")

    shared_by__id = SharedByUser()

    class Meta:
        model = Document
        fields = {
            "id": ID_KWARGS,
            "title": CHAR_KWARGS,
            "content": CHAR_KWARGS,
            "archive_serial_number": INT_KWARGS,
            "created": DATE_KWARGS,
            "added": DATE_KWARGS,
            "modified": DATE_KWARGS,
            "original_filename": CHAR_KWARGS,
            "checksum": CHAR_KWARGS,
            "correspondent": ["isnull"],
            "correspondent__id": ID_KWARGS,
            "correspondent__name": CHAR_KWARGS,
            "tags__id": ID_KWARGS,
            "tags__name": CHAR_KWARGS,
            "document_type": ["isnull"],
            "document_type__id": ID_KWARGS,
            "document_type__name": CHAR_KWARGS,
            "storage_path": ["isnull"],
            "storage_path__id": ID_KWARGS,
            "storage_path__name": CHAR_KWARGS,
            "owner": ["isnull"],
            "owner__id": ID_KWARGS,
            "custom_fields": ["icontains"],
        }


class LogFilterSet(FilterSet):
    class Meta:
        model = Log
        fields = {"level": INT_KWARGS, "created": DATE_KWARGS, "group": ID_KWARGS}


class ShareLinkFilterSet(FilterSet):
    class Meta:
        model = ShareLink
        fields = {
            "created": DATE_KWARGS,
            "expiration": DATE_KWARGS,
        }


class ObjectOwnedOrGrantedPermissionsFilter(ObjectPermissionsFilter):
    """
    A filter backend that limits results to those where the requesting user
    has read object level permissions, owns the objects, or objects without
    an owner (for backwards compat)
    """

    def filter_queryset(self, request, queryset, view):
        objects_with_perms = super().filter_queryset(request, queryset, view)
        objects_owned = queryset.filter(owner=request.user)
        objects_unowned = queryset.filter(owner__isnull=True)
        return objects_with_perms | objects_owned | objects_unowned


class ObjectOwnedPermissionsFilter(ObjectPermissionsFilter):
    """
    A filter backend that limits results to those where the requesting user
    owns the objects or objects without an owner (for backwards compat)
    """

    def filter_queryset(self, request, queryset, view):
        if request.user.is_superuser:
            return queryset
        objects_owned = queryset.filter(owner=request.user)
        objects_unowned = queryset.filter(owner__isnull=True)
        return objects_owned | objects_unowned


class DocumentsOrderingFilter(OrderingFilter):
    field_name = "ordering"
    prefix = "custom_field_"

    def filter_queryset(self, request, queryset, view):
        param = request.query_params.get("ordering")
        if param and self.prefix in param:
            custom_field_id = int(param.split(self.prefix)[1])
            try:
                field = CustomField.objects.get(pk=custom_field_id)
            except CustomField.DoesNotExist:
                raise serializers.ValidationError(
                    {self.prefix + str(custom_field_id): [_("Custom field not found")]},
                )

            annotation = None
            match field.data_type:
                case CustomField.FieldDataType.STRING:
                    annotation = Subquery(
                        CustomFieldInstance.objects.filter(
                            document_id=OuterRef("id"),
                            field_id=custom_field_id,
                        ).values("value_text")[:1],
                    )
                case CustomField.FieldDataType.INT:
                    annotation = Subquery(
                        CustomFieldInstance.objects.filter(
                            document_id=OuterRef("id"),
                            field_id=custom_field_id,
                        ).values("value_int")[:1],
                    )
                case CustomField.FieldDataType.FLOAT:
                    annotation = Subquery(
                        CustomFieldInstance.objects.filter(
                            document_id=OuterRef("id"),
                            field_id=custom_field_id,
                        ).values("value_float")[:1],
                    )
                case CustomField.FieldDataType.DATE:
                    annotation = Subquery(
                        CustomFieldInstance.objects.filter(
                            document_id=OuterRef("id"),
                            field_id=custom_field_id,
                        ).values("value_date")[:1],
                    )
                case CustomField.FieldDataType.MONETARY:
                    annotation = Subquery(
                        CustomFieldInstance.objects.filter(
                            document_id=OuterRef("id"),
                            field_id=custom_field_id,
                        ).values("value_monetary_amount")[:1],
                    )
                case CustomField.FieldDataType.SELECT:
                    # Select options are a little more complicated since the value is the id of the option, not
                    # the label. Additionally, to support sqlite we can't use StringAgg, so we need to create a
                    # case statement for each option, setting the value to the index of the option in a list
                    # sorted by label, and then summing the results to give a single value for the annotation

                    select_options = sorted(
                        field.extra_data.get("select_options", []),
                        key=lambda x: x.get("label"),
                    )
                    whens = [
                        When(
                            custom_fields__field_id=custom_field_id,
                            custom_fields__value_select=option.get("id"),
                            then=Value(idx, output_field=IntegerField()),
                        )
                        for idx, option in enumerate(select_options)
                    ]
                    whens.append(
                        When(
                            custom_fields__field_id=custom_field_id,
                            custom_fields__value_select__isnull=True,
                            then=Value(
                                len(select_options),
                                output_field=IntegerField(),
                            ),
                        ),
                    )
                    annotation = Sum(
                        Case(
                            *whens,
                            default=Value(0),
                            output_field=IntegerField(),
                        ),
                    )
                case CustomField.FieldDataType.DOCUMENTLINK:
                    annotation = Subquery(
                        CustomFieldInstance.objects.filter(
                            document_id=OuterRef("id"),
                            field_id=custom_field_id,
                        ).values("value_document_ids")[:1],
                    )
                case CustomField.FieldDataType.URL:
                    annotation = Subquery(
                        CustomFieldInstance.objects.filter(
                            document_id=OuterRef("id"),
                            field_id=custom_field_id,
                        ).values("value_url")[:1],
                    )
                case CustomField.FieldDataType.BOOL:
                    annotation = Subquery(
                        CustomFieldInstance.objects.filter(
                            document_id=OuterRef("id"),
                            field_id=custom_field_id,
                        ).values("value_bool")[:1],
                    )

            if not annotation:
                # Only happens if a new data type is added and not handled here
                raise ValueError("Invalid custom field data type")

            queryset = (
                queryset.annotate(
                    # We need to annotate the queryset with the custom field value
                    custom_field_value=annotation,
                    # We also need to annotate the queryset with a boolean for sorting whether the field exists
                    has_field=Exists(
                        CustomFieldInstance.objects.filter(
                            document_id=OuterRef("id"),
                            field_id=custom_field_id,
                        ),
                    ),
                )
                .order_by(
                    "-has_field",
                    param.replace(
                        self.prefix + str(custom_field_id),
                        "custom_field_value",
                    ),
                )
                .distinct()
            )

        return super().filter_queryset(request, queryset, view)
