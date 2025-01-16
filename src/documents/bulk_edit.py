import hashlib
import itertools
import logging
import tempfile
from pathlib import Path
from typing import Literal

from celery import chain
from celery import chord
from celery import group
from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q

from documents.data_models import ConsumableDocument
from documents.data_models import DocumentMetadataOverrides
from documents.data_models import DocumentSource
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import StoragePath
from documents.permissions import set_permissions_for_object
from documents.tasks import bulk_update_documents
from documents.tasks import consume_file
from documents.tasks import update_document_content_maybe_archive_file

logger: logging.Logger = logging.getLogger("paperless.bulk_edit")


def set_correspondent(
    doc_ids: list[int],
    correspondent: Correspondent,
) -> Literal["OK"]:
    if correspondent:
        correspondent = Correspondent.objects.only("pk").get(id=correspondent)

    qs = (
        Document.objects.filter(Q(id__in=doc_ids) & ~Q(correspondent=correspondent))
        .select_related("correspondent")
        .only("pk", "correspondent__id")
    )
    affected_docs = list(qs.values_list("pk", flat=True))
    qs.update(correspondent=correspondent)

    bulk_update_documents.delay(document_ids=affected_docs)

    return "OK"


def set_storage_path(doc_ids: list[int], storage_path: StoragePath) -> Literal["OK"]:
    if storage_path:
        storage_path = StoragePath.objects.only("pk").get(id=storage_path)

    qs = (
        Document.objects.filter(
            Q(id__in=doc_ids) & ~Q(storage_path=storage_path),
        )
        .select_related("storage_path")
        .only("pk", "storage_path__id")
    )
    affected_docs = list(qs.values_list("pk", flat=True))
    qs.update(storage_path=storage_path)

    bulk_update_documents.delay(
        document_ids=affected_docs,
    )

    return "OK"


def set_document_type(doc_ids: list[int], document_type: DocumentType) -> Literal["OK"]:
    if document_type:
        document_type = DocumentType.objects.only("pk").get(id=document_type)

    qs = (
        Document.objects.filter(Q(id__in=doc_ids) & ~Q(document_type=document_type))
        .select_related("document_type")
        .only("pk", "document_type__id")
    )
    affected_docs = list(qs.values_list("pk", flat=True))
    qs.update(document_type=document_type)

    bulk_update_documents.delay(document_ids=affected_docs)

    return "OK"


def add_tag(doc_ids: list[int], tag: int) -> Literal["OK"]:
    qs = Document.objects.filter(Q(id__in=doc_ids) & ~Q(tags__id=tag)).only("pk")
    affected_docs = list(qs.values_list("pk", flat=True))

    DocumentTagRelationship = Document.tags.through

    DocumentTagRelationship.objects.bulk_create(
        [DocumentTagRelationship(document_id=doc, tag_id=tag) for doc in affected_docs],
    )

    bulk_update_documents.delay(document_ids=affected_docs)

    return "OK"


def remove_tag(doc_ids: list[int], tag: int) -> Literal["OK"]:
    qs = Document.objects.filter(Q(id__in=doc_ids) & Q(tags__id=tag)).only("pk")
    affected_docs = list(qs.values_list("pk", flat=True))

    DocumentTagRelationship = Document.tags.through

    DocumentTagRelationship.objects.filter(
        Q(document_id__in=affected_docs) & Q(tag_id=tag),
    ).delete()

    bulk_update_documents.delay(document_ids=affected_docs)

    return "OK"


def modify_tags(
    doc_ids: list[int],
    add_tags: list[int],
    remove_tags: list[int],
) -> Literal["OK"]:
    qs = Document.objects.filter(id__in=doc_ids).only("pk")
    affected_docs = list(qs.values_list("pk", flat=True))

    DocumentTagRelationship = Document.tags.through

    DocumentTagRelationship.objects.filter(
        document_id__in=affected_docs,
        tag_id__in=remove_tags,
    ).delete()

    DocumentTagRelationship.objects.bulk_create(
        [
            DocumentTagRelationship(document_id=doc, tag_id=tag)
            for (doc, tag) in itertools.product(affected_docs, add_tags)
        ],
        ignore_conflicts=True,
    )

    bulk_update_documents.delay(document_ids=affected_docs)

    return "OK"


def modify_custom_fields(
    doc_ids: list[int],
    add_custom_fields: list[int] | dict,
    remove_custom_fields: list[int],
) -> Literal["OK"]:
    qs = Document.objects.filter(id__in=doc_ids).only("pk")
    affected_docs = list(qs.values_list("pk", flat=True))
    # Ensure add_custom_fields is a list of tuples, supports old API
    add_custom_fields = (
        add_custom_fields.items()
        if isinstance(add_custom_fields, dict)
        else [(field, None) for field in add_custom_fields]
    )

    custom_fields = CustomField.objects.filter(
        id__in=[int(field) for field, _ in add_custom_fields],
    ).distinct()
    for field_id, value in add_custom_fields:
        for doc_id in affected_docs:
            defaults = {}
            custom_field = custom_fields.get(id=field_id)
            if custom_field:
                value_field = CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    custom_field.data_type
                ]
                defaults[value_field] = value
            CustomFieldInstance.objects.update_or_create(
                document_id=doc_id,
                field_id=field_id,
                defaults=defaults,
            )
    CustomFieldInstance.objects.filter(
        document_id__in=affected_docs,
        field_id__in=remove_custom_fields,
    ).hard_delete()

    bulk_update_documents.delay(document_ids=affected_docs)

    return "OK"


@shared_task
def delete(doc_ids: list[int]) -> Literal["OK"]:
    try:
        Document.objects.filter(id__in=doc_ids).delete()

        from documents import index

        with index.open_index_writer() as writer:
            for id in doc_ids:
                index.remove_document_by_id(writer, id)
    except Exception as e:
        if "Data too long for column" in str(e):
            logger.warning(
                "Detected a possible incompatible database column. See https://docs.paperless-ngx.com/troubleshooting/#convert-uuid-field",
            )
        logger.error(f"Error deleting documents: {e!s}")

    return "OK"


def reprocess(doc_ids: list[int]) -> Literal["OK"]:
    for document_id in doc_ids:
        update_document_content_maybe_archive_file.delay(
            document_id=document_id,
        )

    return "OK"


def set_permissions(
    doc_ids: list[int],
    set_permissions,
    *,
    owner=None,
    merge=False,
) -> Literal["OK"]:
    qs = Document.objects.filter(id__in=doc_ids).select_related("owner")

    if merge:
        # If merging, only set owner for documents that don't have an owner
        qs.filter(owner__isnull=True).update(owner=owner)
    else:
        qs.update(owner=owner)

    for doc in qs:
        set_permissions_for_object(permissions=set_permissions, object=doc, merge=merge)

    affected_docs = list(qs.values_list("pk", flat=True))

    bulk_update_documents.delay(document_ids=affected_docs)

    return "OK"


def rotate(doc_ids: list[int], degrees: int) -> Literal["OK"]:
    logger.info(
        f"Attempting to rotate {len(doc_ids)} documents by {degrees} degrees.",
    )
    qs = Document.objects.filter(id__in=doc_ids)
    affected_docs: list[int] = []
    import pikepdf

    rotate_tasks = []
    for doc in qs:
        if doc.mime_type != "application/pdf":
            logger.warning(
                f"Document {doc.id} is not a PDF, skipping rotation.",
            )
            continue
        try:
            with pikepdf.open(doc.source_path, allow_overwriting_input=True) as pdf:
                for page in pdf.pages:
                    page.rotate(degrees, relative=True)
                pdf.save()
                doc.checksum = hashlib.md5(doc.source_path.read_bytes()).hexdigest()
                doc.save()
                rotate_tasks.append(
                    update_document_content_maybe_archive_file.s(
                        document_id=doc.id,
                    ),
                )
                logger.info(
                    f"Rotated document {doc.id} by {degrees} degrees",
                )
                affected_docs.append(doc.id)
        except Exception as e:
            logger.exception(f"Error rotating document {doc.id}: {e}")

    if len(affected_docs) > 0:
        bulk_update_task = bulk_update_documents.si(document_ids=affected_docs)
        chord(header=rotate_tasks, body=bulk_update_task).delay()

    return "OK"


def merge(
    doc_ids: list[int],
    *,
    metadata_document_id: int | None = None,
    delete_originals: bool = False,
    user: User | None = None,
) -> Literal["OK"]:
    logger.info(
        f"Attempting to merge {len(doc_ids)} documents into a single document.",
    )
    qs = Document.objects.filter(id__in=doc_ids)
    affected_docs: list[int] = []
    import pikepdf

    merged_pdf = pikepdf.new()
    version: str = merged_pdf.pdf_version
    # use doc_ids to preserve order
    for doc_id in doc_ids:
        doc = qs.get(id=doc_id)
        try:
            with pikepdf.open(str(doc.source_path)) as pdf:
                version = max(version, pdf.pdf_version)
                merged_pdf.pages.extend(pdf.pages)
            affected_docs.append(doc.id)
        except Exception as e:
            logger.exception(
                f"Error merging document {doc.id}, it will not be included in the merge: {e}",
            )
    if len(affected_docs) == 0:
        logger.warning("No documents were merged")
        return "OK"

    filepath = (
        Path(
            tempfile.mkdtemp(dir=settings.SCRATCH_DIR),
        )
        / f"{'_'.join([str(doc_id) for doc_id in doc_ids])[:100]}_merged.pdf"
    )
    merged_pdf.remove_unreferenced_resources()
    merged_pdf.save(filepath, min_version=version)
    merged_pdf.close()

    if metadata_document_id:
        metadata_document = qs.get(id=metadata_document_id)
        if metadata_document is not None:
            overrides: DocumentMetadataOverrides = (
                DocumentMetadataOverrides.from_document(metadata_document)
            )
            overrides.title = metadata_document.title + " (merged)"
        else:
            overrides = DocumentMetadataOverrides()
    else:
        overrides = DocumentMetadataOverrides()

    if user is not None:
        overrides.owner_id = user.id

    logger.info("Adding merged document to the task queue.")

    consume_task = consume_file.s(
        ConsumableDocument(
            source=DocumentSource.ConsumeFolder,
            original_file=filepath,
        ),
        overrides,
    )

    if delete_originals:
        logger.info(
            "Queueing removal of original documents after consumption of merged document",
        )
        chain(consume_task, delete.si(affected_docs)).delay()
    else:
        consume_task.delay()

    return "OK"


def split(
    doc_ids: list[int],
    pages: list[list[int]],
    *,
    delete_originals: bool = False,
    user: User | None = None,
) -> Literal["OK"]:
    logger.info(
        f"Attempting to split document {doc_ids[0]} into {len(pages)} documents",
    )
    doc = Document.objects.get(id=doc_ids[0])
    import pikepdf

    consume_tasks = []

    try:
        with pikepdf.open(doc.source_path) as pdf:
            for idx, split_doc in enumerate(pages):
                dst: pikepdf.Pdf = pikepdf.new()
                for page in split_doc:
                    dst.pages.append(pdf.pages[page - 1])
                filepath: Path = (
                    Path(
                        tempfile.mkdtemp(dir=settings.SCRATCH_DIR),
                    )
                    / f"{doc.id}_{split_doc[0]}-{split_doc[-1]}.pdf"
                )
                dst.remove_unreferenced_resources()
                dst.save(filepath)
                dst.close()

                overrides: DocumentMetadataOverrides = (
                    DocumentMetadataOverrides().from_document(doc)
                )
                overrides.title = f"{doc.title} (split {idx + 1})"
                if user is not None:
                    overrides.owner_id = user.id
                logger.info(
                    f"Adding split document with pages {split_doc} to the task queue.",
                )
                consume_tasks.append(
                    consume_file.s(
                        ConsumableDocument(
                            source=DocumentSource.ConsumeFolder,
                            original_file=filepath,
                        ),
                        overrides,
                    ),
                )

            if delete_originals:
                logger.info(
                    "Queueing removal of original document after consumption of the split documents",
                )
                chord(header=consume_tasks, body=delete.si([doc.id])).delay()
            else:
                group(consume_tasks).delay()

    except Exception as e:
        logger.exception(f"Error splitting document {doc.id}: {e}")

    return "OK"


def delete_pages(doc_ids: list[int], pages: list[int]) -> Literal["OK"]:
    logger.info(
        f"Attempting to delete pages {pages} from {len(doc_ids)} documents",
    )
    doc = Document.objects.get(id=doc_ids[0])
    pages = sorted(pages)  # sort pages to avoid index issues
    import pikepdf

    try:
        with pikepdf.open(doc.source_path, allow_overwriting_input=True) as pdf:
            offset = 1  # pages are 1-indexed
            for page_num in pages:
                pdf.pages.remove(pdf.pages[page_num - offset])
                offset += 1  # remove() changes the index of the pages
            pdf.remove_unreferenced_resources()
            pdf.save()
            doc.checksum = hashlib.md5(doc.source_path.read_bytes()).hexdigest()
            if doc.page_count is not None:
                doc.page_count = doc.page_count - len(pages)
            doc.save()
            update_document_content_maybe_archive_file.delay(document_id=doc.id)
            logger.info(f"Deleted pages {pages} from document {doc.id}")
    except Exception as e:
        logger.exception(f"Error deleting pages from document {doc.id}: {e}")

    return "OK"
