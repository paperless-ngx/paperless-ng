import itertools
import json
import logging
import os
import platform
import re
import tempfile
import urllib
import zipfile
from datetime import datetime
from email.encoders import encode_base64
from email.mime.base import MIMEBase
from email.utils import encode_rfc2231
from pathlib import Path
from time import mktime
from unicodedata import normalize
from urllib.parse import quote
from urllib.parse import urlparse

import pathvalidate
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.db import connections
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Case
from django.db.models import Count
from django.db.models import IntegerField
from django.db.models import Max
from django.db.models import Model
from django.db.models import Q
from django.db.models import Sum
from django.db.models import When
from django.db.models.functions import Length
from django.db.models.functions import Lower
from django.db.models.manager import Manager
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseForbidden
from django.http import HttpResponseRedirect
from django.http import HttpResponseServerError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.timezone import make_aware
from django.utils.translation import get_language
from django.views import View
from django.views.decorators.cache import cache_control
from django.views.decorators.http import condition
from django.views.decorators.http import last_modified
from django.views.generic import TemplateView
from django_filters.rest_framework import DjangoFilterBackend
from langdetect import detect
from packaging import version as packaging_version
from redis import Redis
from rest_framework import parsers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.filters import OrderingFilter
from rest_framework.filters import SearchFilter
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import DestroyModelMixin
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from rest_framework.viewsets import ModelViewSet
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.viewsets import ViewSet

from documents import bulk_edit
from documents import index
from documents.bulk_download import ArchiveOnlyStrategy
from documents.bulk_download import OriginalAndArchiveStrategy
from documents.bulk_download import OriginalsOnlyStrategy
from documents.caching import get_metadata_cache
from documents.caching import get_suggestion_cache
from documents.caching import refresh_metadata_cache
from documents.caching import refresh_suggestions_cache
from documents.caching import set_metadata_cache
from documents.caching import set_suggestions_cache
from documents.classifier import load_classifier
from documents.conditionals import metadata_etag
from documents.conditionals import metadata_last_modified
from documents.conditionals import preview_etag
from documents.conditionals import preview_last_modified
from documents.conditionals import suggestions_etag
from documents.conditionals import suggestions_last_modified
from documents.conditionals import thumbnail_last_modified
from documents.data_models import ConsumableDocument
from documents.data_models import DocumentMetadataOverrides
from documents.data_models import DocumentSource
from documents.filters import CorrespondentFilterSet
from documents.filters import CustomFieldFilterSet
from documents.filters import DocumentFilterSet
from documents.filters import DocumentsOrderingFilter
from documents.filters import DocumentTypeFilterSet
from documents.filters import ObjectOwnedOrGrantedPermissionsFilter
from documents.filters import ObjectOwnedPermissionsFilter
from documents.filters import ShareLinkFilterSet
from documents.filters import StoragePathFilterSet
from documents.filters import TagFilterSet
from documents.matching import match_correspondents
from documents.matching import match_document_types
from documents.matching import match_storage_paths
from documents.matching import match_tags
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import Document
from documents.models import DocumentType
from documents.models import Note
from documents.models import PaperlessTask
from documents.models import SavedView
from documents.models import ShareLink
from documents.models import StoragePath
from documents.models import Tag
from documents.models import UiSettings
from documents.models import Workflow
from documents.models import WorkflowAction
from documents.models import WorkflowTrigger
from documents.parsers import get_parser_class_for_mime_type
from documents.parsers import parse_date_generator
from documents.permissions import PaperlessAdminPermissions
from documents.permissions import PaperlessNotePermissions
from documents.permissions import PaperlessObjectPermissions
from documents.permissions import get_objects_for_user_owner_aware
from documents.permissions import has_perms_owner_aware
from documents.permissions import set_permissions_for_object
from documents.serialisers import AcknowledgeTasksViewSerializer
from documents.serialisers import BulkDownloadSerializer
from documents.serialisers import BulkEditObjectsSerializer
from documents.serialisers import BulkEditSerializer
from documents.serialisers import CorrespondentSerializer
from documents.serialisers import CustomFieldSerializer
from documents.serialisers import DocumentListSerializer
from documents.serialisers import DocumentSerializer
from documents.serialisers import DocumentTypeSerializer
from documents.serialisers import PostDocumentSerializer
from documents.serialisers import SavedViewSerializer
from documents.serialisers import SearchResultSerializer
from documents.serialisers import ShareLinkSerializer
from documents.serialisers import StoragePathSerializer
from documents.serialisers import StoragePathTestSerializer
from documents.serialisers import TagSerializer
from documents.serialisers import TagSerializerVersion1
from documents.serialisers import TasksViewSerializer
from documents.serialisers import TrashSerializer
from documents.serialisers import UiSettingsViewSerializer
from documents.serialisers import WorkflowActionSerializer
from documents.serialisers import WorkflowSerializer
from documents.serialisers import WorkflowTriggerSerializer
from documents.signals import document_updated
from documents.tasks import consume_file
from documents.tasks import empty_trash
from documents.templating.filepath import validate_filepath_template_and_render
from paperless import version
from paperless.celery import app as celery_app
from paperless.config import GeneralConfig
from paperless.db import GnuPG
from paperless.serialisers import GroupSerializer
from paperless.serialisers import UserSerializer
from paperless.views import StandardPagination
from paperless_mail.models import MailAccount
from paperless_mail.models import MailRule
from paperless_mail.oauth import PaperlessMailOAuth2Manager
from paperless_mail.serialisers import MailAccountSerializer
from paperless_mail.serialisers import MailRuleSerializer

if settings.AUDIT_LOG_ENABLED:
    from auditlog.models import LogEntry

logger = logging.getLogger("paperless.api")


class IndexView(TemplateView):
    template_name = "index.html"

    def get_frontend_language(self):
        if hasattr(
            self.request.user,
            "ui_settings",
        ) and self.request.user.ui_settings.settings.get("language"):
            lang = self.request.user.ui_settings.settings.get("language")
        else:
            lang = get_language()
        # This is here for the following reason:
        # Django identifies languages in the form "en-us"
        # However, angular generates locales as "en-US".
        # this translates between these two forms.
        if "-" in lang:
            first = lang[: lang.index("-")]
            second = lang[lang.index("-") + 1 :]
            return f"{first}-{second.upper()}"
        else:
            return lang

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cookie_prefix"] = settings.COOKIE_PREFIX
        context["username"] = self.request.user.username
        context["full_name"] = self.request.user.get_full_name()
        context["styles_css"] = f"frontend/{self.get_frontend_language()}/styles.css"
        context["runtime_js"] = f"frontend/{self.get_frontend_language()}/runtime.js"
        context["polyfills_js"] = (
            f"frontend/{self.get_frontend_language()}/polyfills.js"
        )
        context["main_js"] = f"frontend/{self.get_frontend_language()}/main.js"
        context["webmanifest"] = (
            f"frontend/{self.get_frontend_language()}/manifest.webmanifest"
        )
        context["apple_touch_icon"] = (
            f"frontend/{self.get_frontend_language()}/apple-touch-icon.png"
        )
        return context


class PassUserMixin(GenericAPIView):
    """
    Pass a user object to serializer
    """

    def get_serializer(self, *args, **kwargs):
        kwargs.setdefault("user", self.request.user)
        kwargs.setdefault(
            "full_perms",
            self.request.query_params.get("full_perms", False),
        )
        return super().get_serializer(*args, **kwargs)


class PermissionsAwareDocumentCountMixin(PassUserMixin):
    """
    Mixin to add document count to queryset, permissions-aware if needed
    """

    def get_queryset(self):
        filter = (
            Q(documents__deleted_at__isnull=True)
            if self.request.user is None or self.request.user.is_superuser
            else (
                Q(
                    documents__deleted_at__isnull=True,
                    documents__id__in=get_objects_for_user_owner_aware(
                        self.request.user,
                        "documents.view_document",
                        Document,
                    ).values_list("id", flat=True),
                )
            )
        )
        return (
            super()
            .get_queryset()
            .annotate(document_count=Count("documents", filter=filter))
        )


class CorrespondentViewSet(ModelViewSet, PermissionsAwareDocumentCountMixin):
    model = Correspondent

    queryset = Correspondent.objects.select_related("owner").order_by(Lower("name"))

    serializer_class = CorrespondentSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (
        DjangoFilterBackend,
        OrderingFilter,
        ObjectOwnedOrGrantedPermissionsFilter,
    )
    filterset_class = CorrespondentFilterSet
    ordering_fields = (
        "name",
        "matching_algorithm",
        "match",
        "document_count",
        "last_correspondence",
    )

    def list(self, request, *args, **kwargs):
        if request.query_params.get("last_correspondence", None):
            self.queryset = self.queryset.annotate(
                last_correspondence=Max("documents__created"),
            )
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        self.queryset = self.queryset.annotate(
            last_correspondence=Max("documents__created"),
        )
        return super().retrieve(request, *args, **kwargs)


class TagViewSet(ModelViewSet, PermissionsAwareDocumentCountMixin):
    model = Tag

    queryset = Tag.objects.select_related("owner").order_by(
        Lower("name"),
    )

    def get_serializer_class(self, *args, **kwargs):
        if int(self.request.version) == 1:
            return TagSerializerVersion1
        else:
            return TagSerializer

    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (
        DjangoFilterBackend,
        OrderingFilter,
        ObjectOwnedOrGrantedPermissionsFilter,
    )
    filterset_class = TagFilterSet
    ordering_fields = ("color", "name", "matching_algorithm", "match", "document_count")


class DocumentTypeViewSet(ModelViewSet, PermissionsAwareDocumentCountMixin):
    model = DocumentType

    queryset = DocumentType.objects.select_related("owner").order_by(Lower("name"))

    serializer_class = DocumentTypeSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (
        DjangoFilterBackend,
        OrderingFilter,
        ObjectOwnedOrGrantedPermissionsFilter,
    )
    filterset_class = DocumentTypeFilterSet
    ordering_fields = ("name", "matching_algorithm", "match", "document_count")


class DocumentViewSet(
    PassUserMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
    ListModelMixin,
    GenericViewSet,
):
    model = Document
    queryset = Document.objects.annotate(num_notes=Count("notes"))
    serializer_class = DocumentSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (
        DjangoFilterBackend,
        SearchFilter,
        DocumentsOrderingFilter,
        ObjectOwnedOrGrantedPermissionsFilter,
    )
    filterset_class = DocumentFilterSet
    search_fields = ("title", "correspondent__name", "content")
    ordering_fields = (
        "id",
        "title",
        "correspondent__name",
        "document_type__name",
        "created",
        "modified",
        "added",
        "archive_serial_number",
        "num_notes",
        "owner",
        "page_count",
        "custom_field_",
    )

    def get_queryset(self):
        return (
            Document.objects.distinct()
            .order_by("-created")
            .annotate(num_notes=Count("notes"))
            .select_related("correspondent", "storage_path", "document_type", "owner")
            .prefetch_related("tags", "custom_fields", "notes")
        )

    def get_serializer(self, *args, **kwargs):
        fields_param = self.request.query_params.get("fields", None)
        fields = fields_param.split(",") if fields_param else None
        truncate_content = self.request.query_params.get("truncate_content", "False")
        kwargs.setdefault("context", self.get_serializer_context())
        kwargs.setdefault("fields", fields)
        kwargs.setdefault("truncate_content", truncate_content.lower() in ["true", "1"])
        kwargs.setdefault(
            "full_perms",
            self.request.query_params.get("full_perms", False),
        )
        return super().get_serializer(*args, **kwargs)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        from documents import index

        index.add_or_update_document(self.get_object())

        document_updated.send(
            sender=self.__class__,
            document=self.get_object(),
        )

        return response

    def destroy(self, request, *args, **kwargs):
        from documents import index

        index.remove_document_from_index(self.get_object())
        try:
            return super().destroy(request, *args, **kwargs)
        except Exception as e:
            if "Data too long for column" in str(e):
                logger.warning(
                    "Detected a possible incompatible database column. See https://docs.paperless-ngx.com/troubleshooting/#convert-uuid-field",
                )
            logger.error(f"Error deleting document: {e!s}")
            return HttpResponseBadRequest(
                "Error deleting document, check logs for more detail.",
            )

    @staticmethod
    def original_requested(request):
        return (
            "original" in request.query_params
            and request.query_params["original"] == "true"
        )

    def file_response(self, pk, request, disposition):
        doc = Document.global_objects.select_related("owner").get(id=pk)
        if request.user is not None and not has_perms_owner_aware(
            request.user,
            "view_document",
            doc,
        ):
            return HttpResponseForbidden("Insufficient permissions")
        return serve_file(
            doc=doc,
            use_archive=not self.original_requested(request)
            and doc.has_archive_version,
            disposition=disposition,
        )

    def get_metadata(self, file, mime_type):
        if not os.path.isfile(file):
            return None

        parser_class = get_parser_class_for_mime_type(mime_type)
        if parser_class:
            parser = parser_class(progress_callback=None, logging_group=None)

            try:
                return parser.extract_metadata(file, mime_type)
            except Exception:  # pragma: no cover
                logger.exception(f"Issue getting metadata for {file}")
                # TODO: cover GPG errors, remove later.
                return []
        else:  # pragma: no cover
            logger.warning(f"No parser for {mime_type}")
            return []

    def get_filesize(self, filename):
        if os.path.isfile(filename):
            return os.stat(filename).st_size
        else:
            return None

    @action(methods=["get"], detail=True)
    @method_decorator(cache_control(no_cache=True))
    @method_decorator(
        condition(etag_func=metadata_etag, last_modified_func=metadata_last_modified),
    )
    def metadata(self, request, pk=None):
        try:
            doc = Document.objects.select_related("owner").get(pk=pk)
            if request.user is not None and not has_perms_owner_aware(
                request.user,
                "view_document",
                doc,
            ):
                return HttpResponseForbidden("Insufficient permissions")
        except Document.DoesNotExist:
            raise Http404

        document_cached_metadata = get_metadata_cache(doc.pk)

        archive_metadata = None
        archive_filesize = None
        if document_cached_metadata is not None:
            original_metadata = document_cached_metadata.original_metadata
            archive_metadata = document_cached_metadata.archive_metadata
            refresh_metadata_cache(doc.pk)
        else:
            original_metadata = self.get_metadata(doc.source_path, doc.mime_type)

            if doc.has_archive_version:
                archive_filesize = self.get_filesize(doc.archive_path)
                archive_metadata = self.get_metadata(
                    doc.archive_path,
                    "application/pdf",
                )
            set_metadata_cache(doc, original_metadata, archive_metadata)

        meta = {
            "original_checksum": doc.checksum,
            "original_size": self.get_filesize(doc.source_path),
            "original_mime_type": doc.mime_type,
            "media_filename": doc.filename,
            "has_archive_version": doc.has_archive_version,
            "original_metadata": original_metadata,
            "archive_checksum": doc.archive_checksum,
            "archive_media_filename": doc.archive_filename,
            "original_filename": doc.original_filename,
            "archive_size": archive_filesize,
            "archive_metadata": archive_metadata,
        }

        lang = "en"
        try:
            lang = detect(doc.content)
        except Exception:
            pass
        meta["lang"] = lang

        return Response(meta)

    @action(methods=["get"], detail=True)
    @method_decorator(cache_control(no_cache=True))
    @method_decorator(
        condition(
            etag_func=suggestions_etag,
            last_modified_func=suggestions_last_modified,
        ),
    )
    def suggestions(self, request, pk=None):
        doc = get_object_or_404(Document.objects.select_related("owner"), pk=pk)
        if request.user is not None and not has_perms_owner_aware(
            request.user,
            "view_document",
            doc,
        ):
            return HttpResponseForbidden("Insufficient permissions")

        document_suggestions = get_suggestion_cache(doc.pk)

        if document_suggestions is not None:
            refresh_suggestions_cache(doc.pk)
            return Response(document_suggestions.suggestions)

        classifier = load_classifier()

        dates = []
        if settings.NUMBER_OF_SUGGESTED_DATES > 0:
            gen = parse_date_generator(doc.filename, doc.content)
            dates = sorted(
                {i for i in itertools.islice(gen, settings.NUMBER_OF_SUGGESTED_DATES)},
            )

        resp_data = {
            "correspondents": [
                c.id for c in match_correspondents(doc, classifier, request.user)
            ],
            "tags": [t.id for t in match_tags(doc, classifier, request.user)],
            "document_types": [
                dt.id for dt in match_document_types(doc, classifier, request.user)
            ],
            "storage_paths": [
                dt.id for dt in match_storage_paths(doc, classifier, request.user)
            ],
            "dates": [date.strftime("%Y-%m-%d") for date in dates if date is not None],
        }

        # Cache the suggestions and the classifier hash for later
        set_suggestions_cache(doc.pk, resp_data, classifier)

        return Response(resp_data)

    @action(methods=["get"], detail=True)
    @method_decorator(cache_control(no_cache=True))
    @method_decorator(
        condition(etag_func=preview_etag, last_modified_func=preview_last_modified),
    )
    def preview(self, request, pk=None):
        try:
            response = self.file_response(pk, request, "inline")
            return response
        except (FileNotFoundError, Document.DoesNotExist):
            raise Http404

    @action(methods=["get"], detail=True)
    @method_decorator(cache_control(no_cache=True))
    @method_decorator(last_modified(thumbnail_last_modified))
    def thumb(self, request, pk=None):
        try:
            doc = Document.objects.select_related("owner").get(id=pk)
            if request.user is not None and not has_perms_owner_aware(
                request.user,
                "view_document",
                doc,
            ):
                return HttpResponseForbidden("Insufficient permissions")
            if doc.storage_type == Document.STORAGE_TYPE_GPG:
                handle = GnuPG.decrypted(doc.thumbnail_file)
            else:
                handle = doc.thumbnail_file

            return HttpResponse(handle, content_type="image/webp")
        except (FileNotFoundError, Document.DoesNotExist):
            raise Http404

    @action(methods=["get"], detail=True)
    def download(self, request, pk=None):
        try:
            return self.file_response(pk, request, "attachment")
        except (FileNotFoundError, Document.DoesNotExist):
            raise Http404

    def getNotes(self, doc):
        return [
            {
                "id": c.pk,
                "note": c.note,
                "created": c.created,
                "user": {
                    "id": c.user.id,
                    "username": c.user.username,
                    "first_name": c.user.first_name,
                    "last_name": c.user.last_name,
                },
            }
            for c in Note.objects.select_related("user")
            .only(
                "pk",
                "note",
                "created",
                "user__id",
                "user__username",
                "user__first_name",
                "user__last_name",
            )
            .filter(document=doc)
            .order_by("-created")
        ]

    @action(
        methods=["get", "post", "delete"],
        detail=True,
        permission_classes=[PaperlessNotePermissions],
    )
    def notes(self, request, pk=None):
        currentUser = request.user
        try:
            doc = (
                Document.objects.select_related("owner")
                .prefetch_related("notes")
                .only("pk", "owner__id")
                .get(pk=pk)
            )
            if currentUser is not None and not has_perms_owner_aware(
                currentUser,
                "view_document",
                doc,
            ):
                return HttpResponseForbidden("Insufficient permissions to view notes")
        except Document.DoesNotExist:
            raise Http404

        if request.method == "GET":
            try:
                notes = self.getNotes(doc)
                return Response(notes)
            except Exception as e:
                logger.warning(f"An error occurred retrieving notes: {e!s}")
                return Response(
                    {"error": "Error retrieving notes, check logs for more detail."},
                )
        elif request.method == "POST":
            try:
                if currentUser is not None and not has_perms_owner_aware(
                    currentUser,
                    "change_document",
                    doc,
                ):
                    return HttpResponseForbidden(
                        "Insufficient permissions to create notes",
                    )

                c = Note.objects.create(
                    document=doc,
                    note=request.data["note"],
                    user=currentUser,
                )
                # If audit log is enabled make an entry in the log
                # about this note change
                if settings.AUDIT_LOG_ENABLED:
                    LogEntry.objects.log_create(
                        instance=doc,
                        changes={
                            "Note Added": ["None", c.id],
                        },
                        action=LogEntry.Action.UPDATE,
                    )

                doc.modified = timezone.now()
                doc.save()

                from documents import index

                index.add_or_update_document(doc)

                notes = self.getNotes(doc)

                return Response(notes)
            except Exception as e:
                logger.warning(f"An error occurred saving note: {e!s}")
                return Response(
                    {
                        "error": "Error saving note, check logs for more detail.",
                    },
                )
        elif request.method == "DELETE":
            if currentUser is not None and not has_perms_owner_aware(
                currentUser,
                "change_document",
                doc,
            ):
                return HttpResponseForbidden("Insufficient permissions to delete notes")

            note = Note.objects.get(id=int(request.GET.get("id")))
            if settings.AUDIT_LOG_ENABLED:
                LogEntry.objects.log_create(
                    instance=doc,
                    changes={
                        "Note Deleted": [note.id, "None"],
                    },
                    action=LogEntry.Action.UPDATE,
                )

            note.delete()

            doc.modified = timezone.now()
            doc.save()

            from documents import index

            index.add_or_update_document(doc)

            return Response(self.getNotes(doc))

        return Response(
            {
                "error": "error",
            },
        )

    @action(methods=["get"], detail=True)
    def share_links(self, request, pk=None):
        currentUser = request.user
        try:
            doc = Document.objects.select_related("owner").get(pk=pk)
            if currentUser is not None and not has_perms_owner_aware(
                currentUser,
                "change_document",
                doc,
            ):
                return HttpResponseForbidden(
                    "Insufficient permissions to add share link",
                )
        except Document.DoesNotExist:
            raise Http404

        if request.method == "GET":
            now = timezone.now()
            links = [
                {
                    "id": c.pk,
                    "created": c.created,
                    "expiration": c.expiration,
                    "slug": c.slug,
                }
                for c in ShareLink.objects.filter(document=doc)
                .only("pk", "created", "expiration", "slug")
                .exclude(expiration__lt=now)
                .order_by("-created")
            ]
            return Response(links)

    @action(methods=["get"], detail=True, name="Audit Trail")
    def history(self, request, pk=None):
        if not settings.AUDIT_LOG_ENABLED:
            return HttpResponseBadRequest("Audit log is disabled")
        try:
            doc = Document.objects.get(pk=pk)
            if not request.user.has_perm("auditlog.view_logentry") or (
                doc.owner is not None
                and doc.owner != request.user
                and not request.user.is_superuser
            ):
                return HttpResponseForbidden(
                    "Insufficient permissions",
                )
        except Document.DoesNotExist:  # pragma: no cover
            raise Http404

        # documents
        entries = [
            {
                "id": entry.id,
                "timestamp": entry.timestamp,
                "action": entry.get_action_display(),
                "changes": entry.changes,
                "actor": (
                    {"id": entry.actor.id, "username": entry.actor.username}
                    if entry.actor
                    else None
                ),
            }
            for entry in LogEntry.objects.get_for_object(doc).select_related(
                "actor",
            )
        ]

        # custom fields
        for entry in LogEntry.objects.get_for_objects(
            doc.custom_fields.all(),
        ).select_related("actor"):
            entries.append(
                {
                    "id": entry.id,
                    "timestamp": entry.timestamp,
                    "action": entry.get_action_display(),
                    "changes": {
                        "custom_fields": {
                            "type": "custom_field",
                            "field": str(entry.object_repr).split(":")[0].strip(),
                            "value": str(entry.object_repr).split(":")[1].strip(),
                        },
                    },
                    "actor": (
                        {"id": entry.actor.id, "username": entry.actor.username}
                        if entry.actor
                        else None
                    ),
                },
            )

        return Response(sorted(entries, key=lambda x: x["timestamp"], reverse=True))

    @action(methods=["post"], detail=True)
    def email(self, request, pk=None):
        try:
            doc = Document.objects.select_related("owner").get(pk=pk)
            if request.user is not None and not has_perms_owner_aware(
                request.user,
                "view_document",
                doc,
            ):
                return HttpResponseForbidden("Insufficient permissions")
        except Document.DoesNotExist:
            raise Http404

        try:
            if (
                "addresses" not in request.data
                or "subject" not in request.data
                or "message" not in request.data
            ):
                return HttpResponseBadRequest("Missing required fields")

            use_archive_version = request.data.get("use_archive_version", True)

            addresses = request.data.get("addresses").split(",")
            if not all(
                re.match(r"[^@]+@[^@]+\.[^@]+", address.strip())
                for address in addresses
            ):
                return HttpResponseBadRequest("Invalid email address found")

            email = EmailMessage(
                subject=request.data.get("subject"),
                body=request.data.get("message"),
                to=addresses,
            )
            attachment = (
                doc.archive_path
                if use_archive_version and doc.has_archive_version
                else doc.source_path
            )
            with open(attachment, "rb") as f:
                file_content = f.read()

                main_type, sub_type = (
                    doc.mime_type.split("/", 1)
                    if doc.mime_type
                    else ("application", "octet-stream")
                )
                mime_part = MIMEBase(main_type, sub_type)
                mime_part.set_payload(file_content)

                encode_base64(mime_part)

                mime_part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{encode_rfc2231(str(attachment.name))}"',
                )

                email.attach(mime_part)
            email.send()
            logger.debug(
                f"Sent document {doc.id} via email to {addresses}",
            )
            return Response({"message": "Email sent"})
        except Exception as e:
            logger.warning(f"An error occurred emailing document: {e!s}")
            return HttpResponseServerError(
                "Error emailing document, check logs for more detail.",
            )


class UnifiedSearchViewSet(DocumentViewSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.searcher = None

    def get_serializer_class(self):
        if self._is_search_request():
            return SearchResultSerializer
        else:
            return DocumentSerializer

    def _is_search_request(self):
        return (
            "query" in self.request.query_params
            or "more_like_id" in self.request.query_params
        )

    def filter_queryset(self, queryset):
        filtered_queryset = super().filter_queryset(queryset)

        if self._is_search_request():
            from documents import index

            if "query" in self.request.query_params:
                query_class = index.DelayedFullTextQuery
            elif "more_like_id" in self.request.query_params:
                query_class = index.DelayedMoreLikeThisQuery
            else:
                raise ValueError

            return query_class(
                self.searcher,
                self.request.query_params,
                self.paginator.get_page_size(self.request),
                filter_queryset=filtered_queryset,
            )
        else:
            return filtered_queryset

    def list(self, request, *args, **kwargs):
        if self._is_search_request():
            from documents import index

            try:
                with index.open_index_searcher() as s:
                    self.searcher = s
                    return super().list(request)
            except NotFound:
                raise
            except Exception as e:
                logger.warning(f"An error occurred listing search results: {e!s}")
                return HttpResponseBadRequest(
                    "Error listing search results, check logs for more detail.",
                )
        else:
            return super().list(request)

    @action(detail=False, methods=["GET"], name="Get Next ASN")
    def next_asn(self, request, *args, **kwargs):
        max_asn = Document.objects.aggregate(
            Max("archive_serial_number", default=0),
        ).get(
            "archive_serial_number__max",
        )
        return Response(max_asn + 1)


class LogViewSet(ViewSet):
    permission_classes = (IsAuthenticated, PaperlessAdminPermissions)

    log_files = ["paperless", "mail"]

    def get_log_filename(self, log):
        return os.path.join(settings.LOGGING_DIR, f"{log}.log")

    def retrieve(self, request, pk=None, *args, **kwargs):
        if pk not in self.log_files:
            raise Http404

        filename = self.get_log_filename(pk)

        if not os.path.isfile(filename):
            raise Http404

        with open(filename) as f:
            lines = [line.rstrip() for line in f.readlines()]

        return Response(lines)

    def list(self, request, *args, **kwargs):
        exist = [
            log for log in self.log_files if os.path.isfile(self.get_log_filename(log))
        ]
        return Response(exist)


class SavedViewViewSet(ModelViewSet, PassUserMixin):
    model = SavedView

    queryset = SavedView.objects.all()
    serializer_class = SavedViewSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)

    def get_queryset(self):
        user = self.request.user
        return (
            SavedView.objects.filter(owner=user)
            .select_related("owner")
            .prefetch_related("filter_rules")
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class BulkEditView(PassUserMixin):
    MODIFIED_FIELD_BY_METHOD = {
        "set_correspondent": "correspondent",
        "set_document_type": "document_type",
        "set_storage_path": "storage_path",
        "add_tag": "tags",
        "remove_tag": "tags",
        "modify_tags": "tags",
        "modify_custom_fields": "custom_fields",
        "set_permissions": None,
        "delete": "deleted_at",
        "rotate": "checksum",
        "delete_pages": "checksum",
        "split": None,
        "merge": None,
        "reprocess": "checksum",
    }

    permission_classes = (IsAuthenticated,)
    serializer_class = BulkEditSerializer
    parser_classes = (parsers.JSONParser,)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = self.request.user
        method = serializer.validated_data.get("method")
        parameters = serializer.validated_data.get("parameters")
        documents = serializer.validated_data.get("documents")
        if method in [
            bulk_edit.split,
            bulk_edit.merge,
        ]:
            parameters["user"] = user

        if not user.is_superuser:
            document_objs = Document.objects.select_related("owner").filter(
                pk__in=documents,
            )
            user_is_owner_of_all_documents = all(
                (doc.owner == user or doc.owner is None) for doc in document_objs
            )

            # check global and object permissions for all documents
            has_perms = user.has_perm("documents.change_document") and all(
                has_perms_owner_aware(user, "change_document", doc)
                for doc in document_objs
            )

            # check ownership for methods that change original document
            if (
                has_perms
                and method
                in [
                    bulk_edit.set_permissions,
                    bulk_edit.delete,
                    bulk_edit.rotate,
                    bulk_edit.delete_pages,
                ]
            ) or (
                method in [bulk_edit.merge, bulk_edit.split]
                and parameters["delete_originals"]
            ):
                has_perms = user_is_owner_of_all_documents

            # check global add permissions for methods that create documents
            if (
                has_perms
                and method in [bulk_edit.split, bulk_edit.merge]
                and not user.has_perm(
                    "documents.add_document",
                )
            ):
                has_perms = False

            # check global delete permissions for methods that delete documents
            if (
                has_perms
                and (
                    method == bulk_edit.delete
                    or (
                        method in [bulk_edit.merge, bulk_edit.split]
                        and parameters["delete_originals"]
                    )
                )
                and not user.has_perm("documents.delete_document")
            ):
                has_perms = False

            if not has_perms:
                return HttpResponseForbidden("Insufficient permissions")

        try:
            modified_field = self.MODIFIED_FIELD_BY_METHOD.get(method.__name__, None)
            if settings.AUDIT_LOG_ENABLED and modified_field:
                old_documents = {
                    obj["pk"]: obj
                    for obj in Document.objects.filter(pk__in=documents).values(
                        "pk",
                        "correspondent",
                        "document_type",
                        "storage_path",
                        "tags",
                        "custom_fields",
                        "deleted_at",
                        "checksum",
                    )
                }

            # TODO: parameter validation
            result = method(documents, **parameters)

            if settings.AUDIT_LOG_ENABLED and modified_field:
                new_documents = Document.objects.filter(pk__in=documents)
                for doc in new_documents:
                    old_value = old_documents[doc.pk][modified_field]
                    new_value = getattr(doc, modified_field)

                    if isinstance(new_value, Model):
                        # correspondent, document type, etc.
                        new_value = new_value.pk
                    elif isinstance(new_value, Manager):
                        # tags, custom fields
                        new_value = list(new_value.values_list("pk", flat=True))

                    LogEntry.objects.log_create(
                        instance=doc,
                        changes={
                            modified_field: [
                                old_value,
                                new_value,
                            ],
                        },
                        action=LogEntry.Action.UPDATE,
                        actor=user,
                        additional_data={
                            "reason": f"Bulk edit: {method.__name__}",
                        },
                    )

            return Response({"result": result})
        except Exception as e:
            logger.warning(f"An error occurred performing bulk edit: {e!s}")
            return HttpResponseBadRequest(
                "Error performing bulk edit, check logs for more detail.",
            )


class PostDocumentView(GenericAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = PostDocumentSerializer
    parser_classes = (parsers.MultiPartParser,)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        doc_name, doc_data = serializer.validated_data.get("document")
        correspondent_id = serializer.validated_data.get("correspondent")
        document_type_id = serializer.validated_data.get("document_type")
        storage_path_id = serializer.validated_data.get("storage_path")
        tag_ids = serializer.validated_data.get("tags")
        title = serializer.validated_data.get("title")
        created = serializer.validated_data.get("created")
        archive_serial_number = serializer.validated_data.get("archive_serial_number")
        custom_field_ids = serializer.validated_data.get("custom_fields")

        t = int(mktime(datetime.now().timetuple()))

        settings.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

        temp_file_path = Path(tempfile.mkdtemp(dir=settings.SCRATCH_DIR)) / Path(
            pathvalidate.sanitize_filename(doc_name),
        )

        temp_file_path.write_bytes(doc_data)

        os.utime(temp_file_path, times=(t, t))

        input_doc = ConsumableDocument(
            source=DocumentSource.ApiUpload,
            original_file=temp_file_path,
        )
        input_doc_overrides = DocumentMetadataOverrides(
            filename=doc_name,
            title=title,
            correspondent_id=correspondent_id,
            document_type_id=document_type_id,
            storage_path_id=storage_path_id,
            tag_ids=tag_ids,
            created=created,
            asn=archive_serial_number,
            owner_id=request.user.id,
            custom_field_ids=custom_field_ids,
        )

        async_task = consume_file.delay(
            input_doc,
            input_doc_overrides,
        )

        return Response(async_task.id)


class SelectionDataView(GenericAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = DocumentListSerializer
    parser_classes = (parsers.MultiPartParser, parsers.JSONParser)

    def post(self, request, format=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ids = serializer.validated_data.get("documents")

        correspondents = Correspondent.objects.annotate(
            document_count=Count(
                Case(When(documents__id__in=ids, then=1), output_field=IntegerField()),
            ),
        )

        tags = Tag.objects.annotate(
            document_count=Count(
                Case(When(documents__id__in=ids, then=1), output_field=IntegerField()),
            ),
        )

        types = DocumentType.objects.annotate(
            document_count=Count(
                Case(When(documents__id__in=ids, then=1), output_field=IntegerField()),
            ),
        )

        storage_paths = StoragePath.objects.annotate(
            document_count=Count(
                Case(When(documents__id__in=ids, then=1), output_field=IntegerField()),
            ),
        )

        custom_fields = CustomField.objects.annotate(
            document_count=Count(
                Case(
                    When(
                        fields__document__id__in=ids,
                        then=1,
                    ),
                    output_field=IntegerField(),
                ),
            ),
        )

        r = Response(
            {
                "selected_correspondents": [
                    {"id": t.id, "document_count": t.document_count}
                    for t in correspondents
                ],
                "selected_tags": [
                    {"id": t.id, "document_count": t.document_count} for t in tags
                ],
                "selected_document_types": [
                    {"id": t.id, "document_count": t.document_count} for t in types
                ],
                "selected_storage_paths": [
                    {"id": t.id, "document_count": t.document_count}
                    for t in storage_paths
                ],
                "selected_custom_fields": [
                    {"id": t.id, "document_count": t.document_count}
                    for t in custom_fields
                ],
            },
        )

        return r


class SearchAutoCompleteView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, format=None):
        user = self.request.user if hasattr(self.request, "user") else None

        if "term" in request.query_params:
            term = request.query_params["term"]
        else:
            return HttpResponseBadRequest("Term required")

        if "limit" in request.query_params:
            limit = int(request.query_params["limit"])
            if limit <= 0:
                return HttpResponseBadRequest("Invalid limit")
        else:
            limit = 10

        from documents import index

        ix = index.open_index()

        return Response(
            index.autocomplete(
                ix,
                term,
                limit,
                user,
            ),
        )


class GlobalSearchView(PassUserMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = SearchResultSerializer

    def get(self, request, *args, **kwargs):
        query = request.query_params.get("query", None)
        if query is None:
            return HttpResponseBadRequest("Query required")
        elif len(query) < 3:
            return HttpResponseBadRequest("Query must be at least 3 characters")

        db_only = request.query_params.get("db_only", False)

        OBJECT_LIMIT = 3
        docs = []
        if request.user.has_perm("documents.view_document"):
            all_docs = get_objects_for_user_owner_aware(
                request.user,
                "view_document",
                Document,
            )
            # First search by title
            docs = all_docs.filter(title__icontains=query)
            if not db_only and len(docs) < OBJECT_LIMIT:
                # If we don't have enough results, search by content
                from documents import index

                with index.open_index_searcher() as s:
                    fts_query = index.DelayedFullTextQuery(
                        s,
                        request.query_params,
                        OBJECT_LIMIT,
                        filter_queryset=all_docs,
                    )
                    results = fts_query[0:1]
                    docs = docs | Document.objects.filter(
                        id__in=[r["id"] for r in results],
                    )
            docs = docs[:OBJECT_LIMIT]
        saved_views = (
            SavedView.objects.filter(owner=request.user, name__icontains=query)
            if request.user.has_perm("documents.view_savedview")
            else []
        )
        saved_views = saved_views[:OBJECT_LIMIT]
        tags = (
            get_objects_for_user_owner_aware(request.user, "view_tag", Tag).filter(
                name__icontains=query,
            )
            if request.user.has_perm("documents.view_tag")
            else []
        )
        tags = tags[:OBJECT_LIMIT]
        correspondents = (
            get_objects_for_user_owner_aware(
                request.user,
                "view_correspondent",
                Correspondent,
            ).filter(name__icontains=query)
            if request.user.has_perm("documents.view_correspondent")
            else []
        )
        correspondents = correspondents[:OBJECT_LIMIT]
        document_types = (
            get_objects_for_user_owner_aware(
                request.user,
                "view_documenttype",
                DocumentType,
            ).filter(name__icontains=query)
            if request.user.has_perm("documents.view_documenttype")
            else []
        )
        document_types = document_types[:OBJECT_LIMIT]
        storage_paths = (
            get_objects_for_user_owner_aware(
                request.user,
                "view_storagepath",
                StoragePath,
            ).filter(name__icontains=query)
            if request.user.has_perm("documents.view_storagepath")
            else []
        )
        storage_paths = storage_paths[:OBJECT_LIMIT]
        users = (
            User.objects.filter(username__icontains=query)
            if request.user.has_perm("auth.view_user")
            else []
        )
        users = users[:OBJECT_LIMIT]
        groups = (
            Group.objects.filter(name__icontains=query)
            if request.user.has_perm("auth.view_group")
            else []
        )
        groups = groups[:OBJECT_LIMIT]
        mail_rules = (
            MailRule.objects.filter(name__icontains=query)
            if request.user.has_perm("paperless_mail.view_mailrule")
            else []
        )
        mail_rules = mail_rules[:OBJECT_LIMIT]
        mail_accounts = (
            MailAccount.objects.filter(name__icontains=query)
            if request.user.has_perm("paperless_mail.view_mailaccount")
            else []
        )
        mail_accounts = mail_accounts[:OBJECT_LIMIT]
        workflows = (
            Workflow.objects.filter(name__icontains=query)
            if request.user.has_perm("documents.view_workflow")
            else []
        )
        workflows = workflows[:OBJECT_LIMIT]
        custom_fields = (
            CustomField.objects.filter(name__icontains=query)
            if request.user.has_perm("documents.view_customfield")
            else []
        )
        custom_fields = custom_fields[:OBJECT_LIMIT]

        context = {
            "request": request,
        }

        docs_serializer = DocumentSerializer(docs, many=True, context=context)
        saved_views_serializer = SavedViewSerializer(
            saved_views,
            many=True,
            context=context,
        )
        tags_serializer = TagSerializer(tags, many=True, context=context)
        correspondents_serializer = CorrespondentSerializer(
            correspondents,
            many=True,
            context=context,
        )
        document_types_serializer = DocumentTypeSerializer(
            document_types,
            many=True,
            context=context,
        )
        storage_paths_serializer = StoragePathSerializer(
            storage_paths,
            many=True,
            context=context,
        )
        users_serializer = UserSerializer(users, many=True, context=context)
        groups_serializer = GroupSerializer(groups, many=True, context=context)
        mail_rules_serializer = MailRuleSerializer(
            mail_rules,
            many=True,
            context=context,
        )
        mail_accounts_serializer = MailAccountSerializer(
            mail_accounts,
            many=True,
            context=context,
        )
        workflows_serializer = WorkflowSerializer(workflows, many=True, context=context)
        custom_fields_serializer = CustomFieldSerializer(
            custom_fields,
            many=True,
            context=context,
        )

        return Response(
            {
                "total": len(docs)
                + len(saved_views)
                + len(tags)
                + len(correspondents)
                + len(document_types)
                + len(storage_paths)
                + len(users)
                + len(groups)
                + len(mail_rules)
                + len(mail_accounts)
                + len(workflows)
                + len(custom_fields),
                "documents": docs_serializer.data,
                "saved_views": saved_views_serializer.data,
                "tags": tags_serializer.data,
                "correspondents": correspondents_serializer.data,
                "document_types": document_types_serializer.data,
                "storage_paths": storage_paths_serializer.data,
                "users": users_serializer.data,
                "groups": groups_serializer.data,
                "mail_rules": mail_rules_serializer.data,
                "mail_accounts": mail_accounts_serializer.data,
                "workflows": workflows_serializer.data,
                "custom_fields": custom_fields_serializer.data,
            },
        )


class StatisticsView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, format=None):
        user = request.user if request.user is not None else None

        documents = (
            (
                Document.objects.all()
                if user is None
                else get_objects_for_user_owner_aware(
                    user,
                    "documents.view_document",
                    Document,
                )
            )
            .only("mime_type", "content")
            .prefetch_related("tags")
        )
        tags = (
            Tag.objects.all()
            if user is None
            else get_objects_for_user_owner_aware(user, "documents.view_tag", Tag)
        )
        correspondent_count = (
            Correspondent.objects.count()
            if user is None
            else get_objects_for_user_owner_aware(
                user,
                "documents.view_correspondent",
                Correspondent,
            ).count()
        )
        document_type_count = (
            DocumentType.objects.count()
            if user is None
            else get_objects_for_user_owner_aware(
                user,
                "documents.view_documenttype",
                DocumentType,
            ).count()
        )
        storage_path_count = (
            StoragePath.objects.count()
            if user is None
            else get_objects_for_user_owner_aware(
                user,
                "documents.view_storagepath",
                StoragePath,
            ).count()
        )

        documents_total = documents.count()

        inbox_tags = tags.filter(is_inbox_tag=True)

        documents_inbox = (
            documents.filter(tags__id__in=inbox_tags).distinct().count()
            if inbox_tags.exists()
            else None
        )

        document_file_type_counts = (
            documents.values("mime_type")
            .annotate(mime_type_count=Count("mime_type"))
            .order_by("-mime_type_count")
            if documents_total > 0
            else []
        )

        character_count = (
            documents.annotate(
                characters=Length("content"),
            )
            .aggregate(Sum("characters"))
            .get("characters__sum")
        )

        current_asn = Document.objects.aggregate(
            Max("archive_serial_number", default=0),
        ).get(
            "archive_serial_number__max",
        )

        return Response(
            {
                "documents_total": documents_total,
                "documents_inbox": documents_inbox,
                "inbox_tag": (
                    inbox_tags.first().pk if inbox_tags.exists() else None
                ),  # backwards compatibility
                "inbox_tags": (
                    [tag.pk for tag in inbox_tags] if inbox_tags.exists() else None
                ),
                "document_file_type_counts": document_file_type_counts,
                "character_count": character_count,
                "tag_count": len(tags),
                "correspondent_count": correspondent_count,
                "document_type_count": document_type_count,
                "storage_path_count": storage_path_count,
                "current_asn": current_asn,
            },
        )


class BulkDownloadView(GenericAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = BulkDownloadSerializer
    parser_classes = (parsers.JSONParser,)

    def post(self, request, format=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ids = serializer.validated_data.get("documents")
        documents = Document.objects.filter(pk__in=ids)
        compression = serializer.validated_data.get("compression")
        content = serializer.validated_data.get("content")
        follow_filename_format = serializer.validated_data.get("follow_formatting")

        for document in documents:
            if not has_perms_owner_aware(request.user, "view_document", document):
                return HttpResponseForbidden("Insufficient permissions")

        settings.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        temp = tempfile.NamedTemporaryFile(  # noqa: SIM115
            dir=settings.SCRATCH_DIR,
            suffix="-compressed-archive",
            delete=False,
        )

        if content == "both":
            strategy_class = OriginalAndArchiveStrategy
        elif content == "originals":
            strategy_class = OriginalsOnlyStrategy
        else:
            strategy_class = ArchiveOnlyStrategy

        with zipfile.ZipFile(temp.name, "w", compression) as zipf:
            strategy = strategy_class(zipf, follow_filename_format)
            for document in documents:
                strategy.add_document(document)

        # TODO(stumpylog): Investigate using FileResponse here
        with open(temp.name, "rb") as f:
            response = HttpResponse(f, content_type="application/zip")
            response["Content-Disposition"] = '{}; filename="{}"'.format(
                "attachment",
                "documents.zip",
            )

            return response


class StoragePathViewSet(ModelViewSet, PermissionsAwareDocumentCountMixin):
    model = StoragePath

    queryset = StoragePath.objects.select_related("owner").order_by(
        Lower("name"),
    )

    serializer_class = StoragePathSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (
        DjangoFilterBackend,
        OrderingFilter,
        ObjectOwnedOrGrantedPermissionsFilter,
    )
    filterset_class = StoragePathFilterSet
    ordering_fields = ("name", "path", "matching_algorithm", "match", "document_count")

    def get_permissions(self):
        if self.action == "test":
            # Test action does not require object level permissions
            self.permission_classes = (IsAuthenticated,)
        return super().get_permissions()

    def destroy(self, request, *args, **kwargs):
        """
        When a storage path is deleted, see if documents
        using it require a rename/move
        """
        instance = self.get_object()
        doc_ids = [doc.id for doc in instance.documents.all()]

        # perform the deletion so renaming/moving can happen
        response = super().destroy(request, *args, **kwargs)

        if len(doc_ids):
            bulk_edit.bulk_update_documents.delay(doc_ids)

        return response

    @action(methods=["post"], detail=False)
    def test(self, request):
        """
        Test storage path against a document
        """
        serializer = StoragePathTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        document = serializer.validated_data.get("document")
        path = serializer.validated_data.get("path")

        result = validate_filepath_template_and_render(path, document)
        return Response(result)


class UiSettingsView(GenericAPIView):
    queryset = UiSettings.objects.all()
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    serializer_class = UiSettingsViewSerializer

    def get(self, request, format=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.select_related("ui_settings").get(pk=request.user.id)
        ui_settings = {}
        if hasattr(user, "ui_settings"):
            ui_settings = user.ui_settings.settings
        if "update_checking" in ui_settings:
            ui_settings["update_checking"]["backend_setting"] = (
                settings.ENABLE_UPDATE_CHECK
            )
        else:
            ui_settings["update_checking"] = {
                "backend_setting": settings.ENABLE_UPDATE_CHECK,
            }

        ui_settings["trash_delay"] = settings.EMPTY_TRASH_DELAY

        general_config = GeneralConfig()

        ui_settings["app_title"] = settings.APP_TITLE
        if general_config.app_title is not None and len(general_config.app_title) > 0:
            ui_settings["app_title"] = general_config.app_title
        ui_settings["app_logo"] = settings.APP_LOGO
        if general_config.app_logo is not None and len(general_config.app_logo) > 0:
            ui_settings["app_logo"] = general_config.app_logo

        ui_settings["auditlog_enabled"] = settings.AUDIT_LOG_ENABLED

        if settings.GMAIL_OAUTH_ENABLED or settings.OUTLOOK_OAUTH_ENABLED:
            manager = PaperlessMailOAuth2Manager()
            if settings.GMAIL_OAUTH_ENABLED:
                ui_settings["gmail_oauth_url"] = manager.get_gmail_authorization_url()
                request.session["oauth_state"] = manager.state
            if settings.OUTLOOK_OAUTH_ENABLED:
                ui_settings["outlook_oauth_url"] = (
                    manager.get_outlook_authorization_url()
                )
                request.session["oauth_state"] = manager.state

        ui_settings["email_enabled"] = settings.EMAIL_ENABLED

        user_resp = {
            "id": user.id,
            "username": user.username,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "groups": list(user.groups.values_list("id", flat=True)),
        }

        if len(user.first_name) > 0:
            user_resp["first_name"] = user.first_name
        if len(user.last_name) > 0:
            user_resp["last_name"] = user.last_name

        # strip <app_label>.
        roles = map(lambda perm: re.sub(r"^\w+.", "", perm), user.get_all_permissions())
        return Response(
            {
                "user": user_resp,
                "settings": ui_settings,
                "permissions": roles,
            },
        )

    def post(self, request, format=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        serializer.save(user=self.request.user)

        return Response(
            {
                "success": True,
            },
        )


class RemoteVersionView(GenericAPIView):
    def get(self, request, format=None):
        remote_version = "0.0.0"
        is_greater_than_current = False
        current_version = packaging_version.parse(version.__full_version_str__)
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/paperless-ngx/"
                "paperless-ngx/releases/latest",
            )
            # Ensure a JSON response
            req.add_header("Accept", "application/json")

            with urllib.request.urlopen(req) as response:
                remote = response.read().decode("utf8")
            try:
                remote_json = json.loads(remote)
                remote_version = remote_json["tag_name"]
                # Some early tags used ngx-x.y.z
                remote_version = remote_version.removeprefix("ngx-")
            except ValueError:
                logger.debug("An error occurred parsing remote version json")
        except urllib.error.URLError:
            logger.debug("An error occurred checking for available updates")

        is_greater_than_current = (
            packaging_version.parse(
                remote_version,
            )
            > current_version
        )

        return Response(
            {
                "version": remote_version,
                "update_available": is_greater_than_current,
            },
        )


class TasksViewSet(ReadOnlyModelViewSet):
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    serializer_class = TasksViewSerializer
    filter_backends = (ObjectOwnedOrGrantedPermissionsFilter,)

    def get_queryset(self):
        queryset = (
            PaperlessTask.objects.filter(
                acknowledged=False,
            )
            .order_by("date_created")
            .reverse()
        )
        task_id = self.request.query_params.get("task_id")
        if task_id is not None:
            queryset = PaperlessTask.objects.filter(task_id=task_id)
        return queryset

    @action(methods=["post"], detail=False)
    def acknowledge(self, request):
        serializer = AcknowledgeTasksViewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task_ids = serializer.validated_data.get("tasks")

        try:
            tasks = PaperlessTask.objects.filter(id__in=task_ids)
            if request.user is not None and not request.user.is_superuser:
                tasks = tasks.filter(owner=request.user) | tasks.filter(owner=None)
            result = tasks.update(
                acknowledged=True,
            )
            return Response({"result": result})
        except Exception:
            return HttpResponseBadRequest()


class ShareLinkViewSet(ModelViewSet, PassUserMixin):
    model = ShareLink

    queryset = ShareLink.objects.all()

    serializer_class = ShareLinkSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (
        DjangoFilterBackend,
        OrderingFilter,
        ObjectOwnedOrGrantedPermissionsFilter,
    )
    filterset_class = ShareLinkFilterSet
    ordering_fields = ("created", "expiration", "document")


class SharedLinkView(View):
    authentication_classes = []
    permission_classes = []

    def get(self, request, slug):
        share_link = ShareLink.objects.filter(slug=slug).first()
        if share_link is None:
            return HttpResponseRedirect("/accounts/login/?sharelink_notfound=1")
        if share_link.expiration is not None and share_link.expiration < timezone.now():
            return HttpResponseRedirect("/accounts/login/?sharelink_expired=1")
        return serve_file(
            doc=share_link.document,
            use_archive=share_link.file_version == "archive",
            disposition="inline",
        )


def serve_file(doc: Document, use_archive: bool, disposition: str):
    if use_archive:
        file_handle = doc.archive_file
        filename = doc.get_public_filename(archive=True)
        mime_type = "application/pdf"
    else:
        file_handle = doc.source_file
        filename = doc.get_public_filename()
        mime_type = doc.mime_type
        # Support browser previewing csv files by using text mime type
        if mime_type in {"application/csv", "text/csv"} and disposition == "inline":
            mime_type = "text/plain"

    if doc.storage_type == Document.STORAGE_TYPE_GPG:
        file_handle = GnuPG.decrypted(file_handle)

    response = HttpResponse(file_handle, content_type=mime_type)
    # Firefox is not able to handle unicode characters in filename field
    # RFC 5987 addresses this issue
    # see https://datatracker.ietf.org/doc/html/rfc5987#section-4.2
    # Chromium cannot handle commas in the filename
    filename_normalized = normalize("NFKD", filename.replace(",", "_")).encode(
        "ascii",
        "ignore",
    )
    filename_encoded = quote(filename)
    content_disposition = (
        f"{disposition}; "
        f'filename="{filename_normalized}"; '
        f"filename*=utf-8''{filename_encoded}"
    )
    response["Content-Disposition"] = content_disposition
    return response


class BulkEditObjectsView(PassUserMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = BulkEditObjectsSerializer
    parser_classes = (parsers.JSONParser,)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = self.request.user
        object_type = serializer.validated_data.get("object_type")
        object_ids = serializer.validated_data.get("objects")
        object_class = serializer.get_object_class(object_type)
        operation = serializer.validated_data.get("operation")

        objs = object_class.objects.select_related("owner").filter(pk__in=object_ids)

        if not user.is_superuser:
            model_name = object_class._meta.verbose_name
            perm = (
                f"documents.change_{model_name}"
                if operation == "set_permissions"
                else f"documents.delete_{model_name}"
            )
            has_perms = user.has_perm(perm) and all(
                (obj.owner == user or obj.owner is None) for obj in objs
            )

            if not has_perms:
                return HttpResponseForbidden("Insufficient permissions")

        if operation == "set_permissions":
            permissions = serializer.validated_data.get("permissions")
            owner = serializer.validated_data.get("owner")
            merge = serializer.validated_data.get("merge")

            try:
                qs = object_class.objects.filter(id__in=object_ids)

                # if merge is true, we dont want to remove the owner
                if "owner" in serializer.validated_data and (
                    not merge or (merge and owner is not None)
                ):
                    # if merge is true, we dont want to overwrite the owner
                    qs_owner_update = qs.filter(owner__isnull=True) if merge else qs
                    qs_owner_update.update(owner=owner)

                if "permissions" in serializer.validated_data:
                    for obj in qs:
                        set_permissions_for_object(
                            permissions=permissions,
                            object=obj,
                            merge=merge,
                        )

            except Exception as e:
                logger.warning(
                    f"An error occurred performing bulk permissions edit: {e!s}",
                )
                return HttpResponseBadRequest(
                    "Error performing bulk permissions edit, check logs for more detail.",
                )

        elif operation == "delete":
            objs.delete()

        return Response({"result": "OK"})


class WorkflowTriggerViewSet(ModelViewSet):
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)

    serializer_class = WorkflowTriggerSerializer
    pagination_class = StandardPagination

    model = WorkflowTrigger

    queryset = WorkflowTrigger.objects.all()


class WorkflowActionViewSet(ModelViewSet):
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)

    serializer_class = WorkflowActionSerializer
    pagination_class = StandardPagination

    model = WorkflowAction

    queryset = WorkflowAction.objects.all().prefetch_related(
        "assign_tags",
        "assign_view_users",
        "assign_view_groups",
        "assign_change_users",
        "assign_change_groups",
        "assign_custom_fields",
    )


class WorkflowViewSet(ModelViewSet):
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)

    serializer_class = WorkflowSerializer
    pagination_class = StandardPagination

    model = Workflow

    queryset = (
        Workflow.objects.all()
        .order_by("order")
        .prefetch_related(
            "triggers",
            "actions",
        )
    )


class CustomFieldViewSet(ModelViewSet):
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)

    serializer_class = CustomFieldSerializer
    pagination_class = StandardPagination
    filter_backends = (
        DjangoFilterBackend,
        OrderingFilter,
    )
    filterset_class = CustomFieldFilterSet

    model = CustomField

    queryset = CustomField.objects.all().order_by("-created")

    def get_queryset(self):
        filter = (
            Q(fields__document__deleted_at__isnull=True)
            if self.request.user is None or self.request.user.is_superuser
            else (
                Q(
                    fields__document__deleted_at__isnull=True,
                    fields__document__id__in=get_objects_for_user_owner_aware(
                        self.request.user,
                        "documents.view_document",
                        Document,
                    ).values_list("id", flat=True),
                )
            )
        )
        return (
            super()
            .get_queryset()
            .annotate(
                document_count=Count(
                    "fields",
                    filter=filter,
                ),
            )
        )


class SystemStatusView(PassUserMixin):
    permission_classes = (IsAuthenticated,)

    def get(self, request, format=None):
        if not request.user.is_staff:
            return HttpResponseForbidden("Insufficient permissions")

        current_version = version.__full_version_str__

        install_type = "bare-metal"
        if os.environ.get("KUBERNETES_SERVICE_HOST") is not None:
            install_type = "kubernetes"
        elif os.environ.get("PNGX_CONTAINERIZED") == "1":
            install_type = "docker"

        db_conn = connections["default"]
        db_url = db_conn.settings_dict["NAME"]
        db_error = None

        try:
            db_conn.ensure_connection()
            db_status = "OK"
            loader = MigrationLoader(connection=db_conn)
            all_migrations = [f"{app}.{name}" for app, name in loader.graph.nodes]
            applied_migrations = [
                f"{m.app}.{m.name}"
                for m in MigrationRecorder.Migration.objects.all().order_by("id")
            ]
        except Exception as e:  # pragma: no cover
            applied_migrations = []
            db_status = "ERROR"
            logger.exception(
                f"System status detected a possible problem while connecting to the database: {e}",
            )
            db_error = "Error connecting to database, check logs for more detail."

        media_stats = os.statvfs(settings.MEDIA_ROOT)

        redis_url = settings._CHANNELS_REDIS_URL
        redis_url_parsed = urlparse(redis_url)
        redis_constructed_url = f"{redis_url_parsed.scheme}://{redis_url_parsed.path or redis_url_parsed.hostname}"
        if redis_url_parsed.hostname is not None:
            redis_constructed_url += f":{redis_url_parsed.port}"
        redis_error = None
        with Redis.from_url(url=redis_url) as client:
            try:
                client.ping()
                redis_status = "OK"
            except Exception as e:
                redis_status = "ERROR"
                logger.exception(
                    f"System status detected a possible problem while connecting to redis: {e}",
                )
                redis_error = "Error connecting to redis, check logs for more detail."

        try:
            celery_ping = celery_app.control.inspect().ping()
            first_worker_ping = celery_ping[next(iter(celery_ping.keys()))]
            if first_worker_ping["ok"] == "pong":
                celery_active = "OK"
        except Exception:
            celery_active = "ERROR"

        index_error = None
        try:
            ix = index.open_index()
            index_status = "OK"
            index_last_modified = make_aware(
                datetime.fromtimestamp(ix.last_modified()),
            )
        except Exception as e:
            index_status = "ERROR"
            index_error = "Error opening index, check logs for more detail."
            logger.exception(
                f"System status detected a possible problem while opening the index: {e}",
            )
            index_last_modified = None

        classifier_error = None
        classifier_status = None
        try:
            classifier = load_classifier(raise_exception=True)
            if classifier is None:
                # Make sure classifier should exist
                docs_queryset = Document.objects.exclude(
                    tags__is_inbox_tag=True,
                )
                if (
                    docs_queryset.count() > 0
                    and (
                        Tag.objects.filter(matching_algorithm=Tag.MATCH_AUTO).exists()
                        or DocumentType.objects.filter(
                            matching_algorithm=Tag.MATCH_AUTO,
                        ).exists()
                        or Correspondent.objects.filter(
                            matching_algorithm=Tag.MATCH_AUTO,
                        ).exists()
                        or StoragePath.objects.filter(
                            matching_algorithm=Tag.MATCH_AUTO,
                        ).exists()
                    )
                    and not settings.MODEL_FILE.exists()
                ):
                    # if classifier file doesn't exist just classify as a warning
                    classifier_error = "Classifier file does not exist (yet). Re-training may be pending."
                    classifier_status = "WARNING"
                    raise FileNotFoundError(classifier_error)
            classifier_status = "OK"
            task_result_model = apps.get_model("django_celery_results", "taskresult")
            result = (
                task_result_model.objects.filter(
                    task_name="documents.tasks.train_classifier",
                    status="SUCCESS",
                )
                .order_by(
                    "-date_done",
                )
                .first()
            )
            classifier_last_trained = result.date_done if result else None
        except Exception as e:
            if classifier_status is None:
                classifier_status = "ERROR"
            classifier_last_trained = None
            if classifier_error is None:
                classifier_error = (
                    "Unable to load classifier, check logs for more detail."
                )
            logger.exception(
                f"System status detected a possible problem while loading the classifier: {e}",
            )

        return Response(
            {
                "pngx_version": current_version,
                "server_os": platform.platform(),
                "install_type": install_type,
                "storage": {
                    "total": media_stats.f_frsize * media_stats.f_blocks,
                    "available": media_stats.f_frsize * media_stats.f_bavail,
                },
                "database": {
                    "type": db_conn.vendor,
                    "url": db_url,
                    "status": db_status,
                    "error": db_error,
                    "migration_status": {
                        "latest_migration": applied_migrations[-1],
                        "unapplied_migrations": [
                            m for m in all_migrations if m not in applied_migrations
                        ],
                    },
                },
                "tasks": {
                    "redis_url": redis_constructed_url,
                    "redis_status": redis_status,
                    "redis_error": redis_error,
                    "celery_status": celery_active,
                    "index_status": index_status,
                    "index_last_modified": index_last_modified,
                    "index_error": index_error,
                    "classifier_status": classifier_status,
                    "classifier_last_trained": classifier_last_trained,
                    "classifier_error": classifier_error,
                },
            },
        )


class TrashView(ListModelMixin, PassUserMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = TrashSerializer
    filter_backends = (ObjectOwnedPermissionsFilter,)
    pagination_class = StandardPagination

    model = Document

    queryset = Document.deleted_objects.all()

    def get(self, request, format=None):
        self.serializer_class = DocumentSerializer
        return self.list(request, format)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        doc_ids = serializer.validated_data.get("documents")
        docs = (
            Document.global_objects.filter(id__in=doc_ids)
            if doc_ids is not None
            else self.filter_queryset(self.get_queryset()).all()
        )
        for doc in docs:
            if not has_perms_owner_aware(request.user, "delete_document", doc):
                return HttpResponseForbidden("Insufficient permissions")
        action = serializer.validated_data.get("action")
        if action == "restore":
            for doc in Document.deleted_objects.filter(id__in=doc_ids).all():
                doc.restore(strict=False)
        elif action == "empty":
            if doc_ids is None:
                doc_ids = [doc.id for doc in docs]
            empty_trash(doc_ids=doc_ids)
        return Response({"result": "OK", "doc_ids": doc_ids})
