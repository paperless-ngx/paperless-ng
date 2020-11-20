from django.contrib import admin
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from whoosh.writing import AsyncWriter

from . import index
from .models import Correspondent, Document, DocumentType, Log, Tag


class CorrespondentAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "match",
        "matching_algorithm"
    )
    list_filter = ("matching_algorithm",)
    list_editable = ("match", "matching_algorithm")

    readonly_fields = ("slug",)


class TagAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "colour",
        "match",
        "matching_algorithm"
    )
    list_filter = ("colour", "matching_algorithm")
    list_editable = ("colour", "match", "matching_algorithm")

    readonly_fields = ("slug", )


class DocumentTypeAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "match",
        "matching_algorithm"
    )
    list_filter = ("matching_algorithm",)
    list_editable = ("match", "matching_algorithm")

    readonly_fields = ("slug",)


class DocumentAdmin(admin.ModelAdmin):

    search_fields = ("correspondent__name", "title", "content", "tags__name")
    readonly_fields = ("added", "mime_type", "storage_type", "filename")
    list_display = (
        "title",
        "created",
        "added",
        "correspondent",
        "tags_",
        "archive_serial_number",
        "document_type"
    )
    list_filter = (
        "document_type",
        "tags",
        "correspondent"
    )

    filter_horizontal = ("tags",)

    ordering = ["-created", "correspondent"]

    date_hierarchy = "created"

    def has_add_permission(self, request):
        return False

    def created_(self, obj):
        return obj.created.date().strftime("%Y-%m-%d")
    created_.short_description = "Created"

    def delete_queryset(self, request, queryset):
        ix = index.open_index()
        with AsyncWriter(ix) as writer:
            for o in queryset:
                index.remove_document(writer, o)
        super(DocumentAdmin, self).delete_queryset(request, queryset)

    def delete_model(self, request, obj):
        index.remove_document_from_index(obj)
        super(DocumentAdmin, self).delete_model(request, obj)

    def save_model(self, request, obj, form, change):
        index.add_or_update_document(obj)
        super(DocumentAdmin, self).save_model(request, obj, form, change)

    @mark_safe
    def tags_(self, obj):
        r = ""
        for tag in obj.tags.all():
            r += self._html_tag(
                "span",
                tag.slug + ", "
            )
        return r

    @staticmethod
    def _html_tag(kind, inside=None, **kwargs):
        attributes = format_html_join(' ', '{}="{}"', kwargs.items())

        if inside is not None:
            return format_html("<{kind} {attributes}>{inside}</{kind}>",
                               kind=kind, attributes=attributes, inside=inside)

        return format_html("<{} {}/>", kind, attributes)


class LogAdmin(admin.ModelAdmin):

    list_display = ("created", "message", "level",)
    list_filter = ("level", "created",)


admin.site.register(Correspondent, CorrespondentAdmin)
admin.site.register(Tag, TagAdmin)
admin.site.register(DocumentType, DocumentTypeAdmin)
admin.site.register(Document, DocumentAdmin)
admin.site.register(Log, LogAdmin)
