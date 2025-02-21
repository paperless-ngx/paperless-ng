import hashlib
import logging
import shutil
import uuid
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from celery import Task
from celery import shared_task
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db import transaction
from django.db.models.signals import post_save
from django.utils import timezone
from filelock import FileLock
from rich.progress import track
from whoosh.writing import AsyncWriter

from documents import index
from documents import sanity_checker
from documents.barcodes import BarcodePlugin
from documents.caching import clear_document_caches
from documents.classifier import DocumentClassifier
from documents.classifier import load_classifier
from documents.consumer import ConsumerPlugin
from documents.consumer import WorkflowTriggerPlugin
from documents.data_models import ConsumableDocument
from documents.data_models import DocumentMetadataOverrides
from documents.double_sided import CollatePlugin
from documents.file_handling import create_source_path_directory
from documents.file_handling import generate_unique_filename
from documents.models import Correspondent
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import StoragePath
from documents.models import Tag
from documents.models import Workflow
from documents.models import WorkflowRun
from documents.models import WorkflowTrigger
from documents.parsers import DocumentParser
from documents.parsers import get_parser_class_for_mime_type
from documents.plugins.base import ConsumeTaskPlugin
from documents.plugins.base import ProgressManager
from documents.plugins.base import StopConsumeTaskError
from documents.plugins.helpers import ProgressStatusOptions
from documents.sanity_checker import SanityCheckFailedException
from documents.signals import document_updated
from documents.signals.handlers import cleanup_document_deletion
from documents.signals.handlers import run_workflows

if settings.AUDIT_LOG_ENABLED:
    from auditlog.models import LogEntry
logger = logging.getLogger("paperless.tasks")


@shared_task
def index_optimize():
    ix = index.open_index()
    writer = AsyncWriter(ix)
    writer.commit(optimize=True)


def index_reindex(*, progress_bar_disable=False):
    documents = Document.objects.all()

    ix = index.open_index(recreate=True)

    with AsyncWriter(ix) as writer:
        for document in track(
            documents,
            total=documents.count(),
            description="Indexing...",
            disable=progress_bar_disable,
        ):
            index.update_document(writer, document)


@shared_task
def train_classifier():
    if (
        not Tag.objects.filter(matching_algorithm=Tag.MATCH_AUTO).exists()
        and not DocumentType.objects.filter(matching_algorithm=Tag.MATCH_AUTO).exists()
        and not Correspondent.objects.filter(matching_algorithm=Tag.MATCH_AUTO).exists()
        and not StoragePath.objects.filter(matching_algorithm=Tag.MATCH_AUTO).exists()
    ):
        logger.info("No automatic matching items, not training")
        # Special case, items were once auto and trained, so remove the model
        # and prevent its use again
        if settings.MODEL_FILE.exists():
            logger.info(f"Removing {settings.MODEL_FILE} so it won't be used")
            settings.MODEL_FILE.unlink()
        return

    classifier = load_classifier()

    if not classifier:
        classifier = DocumentClassifier()

    try:
        if classifier.train():
            logger.info(
                f"Saving updated classifier model to {settings.MODEL_FILE}...",
            )
            classifier.save()
        else:
            logger.debug("Training data unchanged.")

    except Exception as e:
        logger.warning("Classifier error: " + str(e))


@shared_task(bind=True)
def consume_file(
    self: Task,
    input_doc: ConsumableDocument,
    overrides: DocumentMetadataOverrides | None = None,
):
    # Default no overrides
    if overrides is None:
        overrides = DocumentMetadataOverrides()

    plugins: list[type[ConsumeTaskPlugin]] = [
        CollatePlugin,
        BarcodePlugin,
        WorkflowTriggerPlugin,
        ConsumerPlugin,
    ]

    with (
        ProgressManager(
            overrides.filename or input_doc.original_file.name,
            self.request.id,
        ) as status_mgr,
        TemporaryDirectory(dir=settings.SCRATCH_DIR) as tmp_dir,
    ):
        tmp_dir = Path(tmp_dir)
        for plugin_class in plugins:
            plugin_name = plugin_class.NAME

            plugin = plugin_class(
                input_doc,
                overrides,
                status_mgr,
                tmp_dir,
                self.request.id,
            )

            if not plugin.able_to_run:
                logger.debug(f"Skipping plugin {plugin_name}")
                continue

            try:
                logger.debug(f"Executing plugin {plugin_name}")
                plugin.setup()

                msg = plugin.run()

                if msg is not None:
                    logger.info(f"{plugin_name} completed with: {msg}")
                else:
                    logger.info(f"{plugin_name} completed with no message")

                overrides = plugin.metadata

            except StopConsumeTaskError as e:
                logger.info(f"{plugin_name} requested task exit: {e.message}")
                return e.message

            except Exception as e:
                logger.exception(f"{plugin_name} failed: {e}")
                status_mgr.send_progress(ProgressStatusOptions.FAILED, f"{e}", 100, 100)
                raise

            finally:
                plugin.cleanup()

    return msg


@shared_task
def sanity_check():
    messages = sanity_checker.check_sanity()

    messages.log_messages()

    if messages.has_error:
        raise SanityCheckFailedException("Sanity check failed with errors. See log.")
    elif messages.has_warning:
        return "Sanity check exited with warnings. See log."
    elif len(messages) > 0:
        return "Sanity check exited with infos. See log."
    else:
        return "No issues detected."


@shared_task
def bulk_update_documents(document_ids):
    documents = Document.objects.filter(id__in=document_ids)

    ix = index.open_index()

    for doc in documents:
        clear_document_caches(doc.pk)
        document_updated.send(
            sender=None,
            document=doc,
            logging_group=uuid.uuid4(),
        )
        post_save.send(Document, instance=doc, created=False)

    with AsyncWriter(ix) as writer:
        for doc in documents:
            index.update_document(writer, doc)


@shared_task
def update_document_content_maybe_archive_file(document_id):
    """
    Re-creates OCR content and thumbnail for a document, and archive file if
    it exists.
    """
    document = Document.objects.get(id=document_id)

    mime_type = document.mime_type

    parser_class: type[DocumentParser] = get_parser_class_for_mime_type(mime_type)

    if not parser_class:
        logger.error(
            f"No parser found for mime type {mime_type}, cannot "
            f"archive document {document} (ID: {document_id})",
        )
        return

    parser: DocumentParser = parser_class(logging_group=uuid.uuid4())

    try:
        parser.parse(document.source_path, mime_type, document.get_public_filename())

        thumbnail = parser.get_thumbnail(
            document.source_path,
            mime_type,
            document.get_public_filename(),
        )

        with transaction.atomic():
            oldDocument = Document.objects.get(pk=document.pk)
            if parser.get_archive_path():
                with open(parser.get_archive_path(), "rb") as f:
                    checksum = hashlib.md5(f.read()).hexdigest()
                # I'm going to save first so that in case the file move
                # fails, the database is rolled back.
                # We also don't use save() since that triggers the filehandling
                # logic, and we don't want that yet (file not yet in place)
                document.archive_filename = generate_unique_filename(
                    document,
                    archive_filename=True,
                )
                Document.objects.filter(pk=document.pk).update(
                    archive_checksum=checksum,
                    content=parser.get_text(),
                    archive_filename=document.archive_filename,
                )
                newDocument = Document.objects.get(pk=document.pk)
                if settings.AUDIT_LOG_ENABLED:
                    LogEntry.objects.log_create(
                        instance=oldDocument,
                        changes={
                            "content": [oldDocument.content, newDocument.content],
                            "archive_checksum": [
                                oldDocument.archive_checksum,
                                newDocument.archive_checksum,
                            ],
                            "archive_filename": [
                                oldDocument.archive_filename,
                                newDocument.archive_filename,
                            ],
                        },
                        additional_data={
                            "reason": "Update document content",
                        },
                        action=LogEntry.Action.UPDATE,
                    )
            else:
                Document.objects.filter(pk=document.pk).update(
                    content=parser.get_text(),
                )

                if settings.AUDIT_LOG_ENABLED:
                    LogEntry.objects.log_create(
                        instance=oldDocument,
                        changes={
                            "content": [oldDocument.content, parser.get_text()],
                        },
                        additional_data={
                            "reason": "Update document content",
                        },
                        action=LogEntry.Action.UPDATE,
                    )

            with FileLock(settings.MEDIA_LOCK):
                if parser.get_archive_path():
                    create_source_path_directory(document.archive_path)
                    shutil.move(parser.get_archive_path(), document.archive_path)
                shutil.move(thumbnail, document.thumbnail_path)

        document.refresh_from_db()
        logger.info(
            f"Updating index for document {document_id} ({document.archive_checksum})",
        )
        with index.open_index_writer() as writer:
            index.update_document(writer, document)

        clear_document_caches(document.pk)

    except Exception:
        logger.exception(
            f"Error while parsing document {document} (ID: {document_id})",
        )
    finally:
        parser.cleanup()


@shared_task
def empty_trash(doc_ids=None):
    if doc_ids is None:
        logger.info("Emptying trash of all expired documents")
    documents = (
        Document.deleted_objects.filter(id__in=doc_ids)
        if doc_ids is not None
        else Document.deleted_objects.filter(
            deleted_at__lt=timezone.localtime(timezone.now())
            - timedelta(
                days=settings.EMPTY_TRASH_DELAY,
            ),
        )
    )

    try:
        deleted_document_ids = list(documents.values_list("id", flat=True))
        # Temporarily connect the cleanup handler
        models.signals.post_delete.connect(cleanup_document_deletion, sender=Document)
        documents.delete()  # this is effectively a hard delete
        logger.info(f"Deleted {len(deleted_document_ids)} documents from trash")

        if settings.AUDIT_LOG_ENABLED:
            # Delete the audit log entries for documents that dont exist anymore
            LogEntry.objects.filter(
                content_type=ContentType.objects.get_for_model(Document),
                object_id__in=deleted_document_ids,
            ).delete()
    except Exception as e:  # pragma: no cover
        logger.exception(f"Error while emptying trash: {e}")
    finally:
        models.signals.post_delete.disconnect(
            cleanup_document_deletion,
            sender=Document,
        )


@shared_task
def check_scheduled_workflows():
    scheduled_workflows: list[Workflow] = (
        Workflow.objects.filter(
            triggers__type=WorkflowTrigger.WorkflowTriggerType.SCHEDULED,
            enabled=True,
        )
        .distinct()
        .prefetch_related("triggers")
    )
    if scheduled_workflows.count() > 0:
        logger.debug(f"Checking {len(scheduled_workflows)} scheduled workflows")
        for workflow in scheduled_workflows:
            schedule_triggers = workflow.triggers.filter(
                type=WorkflowTrigger.WorkflowTriggerType.SCHEDULED,
            )
            trigger: WorkflowTrigger
            for trigger in schedule_triggers:
                documents = Document.objects.none()
                offset_td = timedelta(days=trigger.schedule_offset_days)
                logger.debug(
                    f"Checking trigger {trigger} with offset {offset_td} against field: {trigger.schedule_date_field}",
                )
                match trigger.schedule_date_field:
                    case WorkflowTrigger.ScheduleDateField.ADDED:
                        documents = Document.objects.filter(
                            added__lt=timezone.now() - offset_td,
                        )
                    case WorkflowTrigger.ScheduleDateField.CREATED:
                        documents = Document.objects.filter(
                            created__lt=timezone.now() - offset_td,
                        )
                    case WorkflowTrigger.ScheduleDateField.MODIFIED:
                        documents = Document.objects.filter(
                            modified__lt=timezone.now() - offset_td,
                        )
                    case WorkflowTrigger.ScheduleDateField.CUSTOM_FIELD:
                        cf_instances = CustomFieldInstance.objects.filter(
                            field=trigger.schedule_date_custom_field,
                            value_date__lt=timezone.now() - offset_td,
                        )
                        documents = Document.objects.filter(
                            id__in=cf_instances.values_list("document", flat=True),
                        )
                if documents.count() > 0:
                    logger.debug(
                        f"Found {documents.count()} documents for trigger {trigger}",
                    )
                    for document in documents:
                        workflow_runs = WorkflowRun.objects.filter(
                            document=document,
                            type=WorkflowTrigger.WorkflowTriggerType.SCHEDULED,
                            workflow=workflow,
                        ).order_by("-run_at")
                        if not trigger.schedule_is_recurring and workflow_runs.exists():
                            # schedule is non-recurring and the workflow has already been run
                            logger.debug(
                                f"Skipping document {document} for non-recurring workflow {workflow} as it has already been run",
                            )
                            continue
                        elif (
                            trigger.schedule_is_recurring
                            and workflow_runs.exists()
                            and (
                                workflow_runs.last().run_at
                                > timezone.now()
                                - timedelta(
                                    days=trigger.schedule_recurring_interval_days,
                                )
                            )
                        ):
                            # schedule is recurring but the last run was within the number of recurring interval days
                            logger.debug(
                                f"Skipping document {document} for recurring workflow {workflow} as the last run was within the recurring interval",
                            )
                            continue
                        run_workflows(
                            WorkflowTrigger.WorkflowTriggerType.SCHEDULED,
                            document,
                        )
