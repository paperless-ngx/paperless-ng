import logging
import os
import shutil
from pathlib import Path

import httpx
from celery import shared_task
from celery import states
from celery.signals import before_task_publish
from celery.signals import task_failure
from celery.signals import task_postrun
from celery.signals import task_prerun
from django.conf import settings
from django.contrib.auth.models import User
from django.db import DatabaseError
from django.db import close_old_connections
from django.db import models
from django.db.models import Q
from django.dispatch import receiver
from django.utils import timezone
from filelock import FileLock
from guardian.shortcuts import remove_perm

from documents import matching
from documents.caching import clear_document_caches
from documents.classifier import DocumentClassifier
from documents.data_models import ConsumableDocument
from documents.data_models import DocumentMetadataOverrides
from documents.file_handling import create_source_path_directory
from documents.file_handling import delete_empty_directories
from documents.file_handling import generate_unique_filename
from documents.mail import send_email
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import MatchingModel
from documents.models import PaperlessTask
from documents.models import Tag
from documents.models import Workflow
from documents.models import WorkflowAction
from documents.models import WorkflowRun
from documents.models import WorkflowTrigger
from documents.permissions import get_objects_for_user_owner_aware
from documents.permissions import set_permissions_for_object
from documents.templating.workflows import parse_w_workflow_placeholders

logger = logging.getLogger("paperless.handlers")


def add_inbox_tags(sender, document: Document, logging_group=None, **kwargs):
    if document.owner is not None:
        tags = get_objects_for_user_owner_aware(
            document.owner,
            "documents.view_tag",
            Tag,
        )
    else:
        tags = Tag.objects.all()
    inbox_tags = tags.filter(is_inbox_tag=True)
    document.tags.add(*inbox_tags)


def _suggestion_printer(
    stdout,
    style_func,
    suggestion_type: str,
    document: Document,
    selected: MatchingModel,
    base_url: str | None = None,
):
    """
    Smaller helper to reduce duplication when just outputting suggestions to the console
    """
    doc_str = str(document)
    if base_url is not None:
        stdout.write(style_func.SUCCESS(doc_str))
        stdout.write(style_func.SUCCESS(f"{base_url}/documents/{document.pk}"))
    else:
        stdout.write(style_func.SUCCESS(f"{doc_str} [{document.pk}]"))
    stdout.write(f"Suggest {suggestion_type}: {selected}")


def set_correspondent(
    sender,
    document: Document,
    logging_group=None,
    classifier: DocumentClassifier | None = None,
    replace=False,
    use_first=True,
    suggest=False,
    base_url=None,
    stdout=None,
    style_func=None,
    **kwargs,
):
    if document.correspondent and not replace:
        return

    potential_correspondents = matching.match_correspondents(document, classifier)

    potential_count = len(potential_correspondents)
    selected = potential_correspondents[0] if potential_correspondents else None
    if potential_count > 1:
        if use_first:
            logger.debug(
                f"Detected {potential_count} potential correspondents, "
                f"so we've opted for {selected}",
                extra={"group": logging_group},
            )
        else:
            logger.debug(
                f"Detected {potential_count} potential correspondents, "
                f"not assigning any correspondent",
                extra={"group": logging_group},
            )
            return

    if selected or replace:
        if suggest:
            _suggestion_printer(
                stdout,
                style_func,
                "correspondent",
                document,
                selected,
                base_url,
            )
        else:
            logger.info(
                f"Assigning correspondent {selected} to {document}",
                extra={"group": logging_group},
            )

            document.correspondent = selected
            document.save(update_fields=("correspondent",))


def set_document_type(
    sender,
    document: Document,
    logging_group=None,
    classifier: DocumentClassifier | None = None,
    replace=False,
    use_first=True,
    suggest=False,
    base_url=None,
    stdout=None,
    style_func=None,
    **kwargs,
):
    if document.document_type and not replace:
        return

    potential_document_type = matching.match_document_types(document, classifier)

    potential_count = len(potential_document_type)
    selected = potential_document_type[0] if potential_document_type else None

    if potential_count > 1:
        if use_first:
            logger.info(
                f"Detected {potential_count} potential document types, "
                f"so we've opted for {selected}",
                extra={"group": logging_group},
            )
        else:
            logger.info(
                f"Detected {potential_count} potential document types, "
                f"not assigning any document type",
                extra={"group": logging_group},
            )
            return

    if selected or replace:
        if suggest:
            _suggestion_printer(
                stdout,
                style_func,
                "document type",
                document,
                selected,
                base_url,
            )
        else:
            logger.info(
                f"Assigning document type {selected} to {document}",
                extra={"group": logging_group},
            )

            document.document_type = selected
            document.save(update_fields=("document_type",))


def set_tags(
    sender,
    document: Document,
    logging_group=None,
    classifier: DocumentClassifier | None = None,
    replace=False,
    suggest=False,
    base_url=None,
    stdout=None,
    style_func=None,
    **kwargs,
):
    if replace:
        Document.tags.through.objects.filter(document=document).exclude(
            Q(tag__is_inbox_tag=True),
        ).exclude(
            Q(tag__match="") & ~Q(tag__matching_algorithm=Tag.MATCH_AUTO),
        ).delete()

    current_tags = set(document.tags.all())

    matched_tags = matching.match_tags(document, classifier)

    relevant_tags = set(matched_tags) - current_tags

    if suggest:
        extra_tags = current_tags - set(matched_tags)
        extra_tags = [
            t for t in extra_tags if t.matching_algorithm == MatchingModel.MATCH_AUTO
        ]
        if not relevant_tags and not extra_tags:
            return
        doc_str = style_func.SUCCESS(str(document))
        if base_url:
            stdout.write(doc_str)
            stdout.write(f"{base_url}/documents/{document.pk}")
        else:
            stdout.write(doc_str + style_func.SUCCESS(f" [{document.pk}]"))
        if relevant_tags:
            stdout.write("Suggest tags: " + ", ".join([t.name for t in relevant_tags]))
        if extra_tags:
            stdout.write("Extra tags: " + ", ".join([t.name for t in extra_tags]))
    else:
        if not relevant_tags:
            return

        message = 'Tagging "{}" with "{}"'
        logger.info(
            message.format(document, ", ".join([t.name for t in relevant_tags])),
            extra={"group": logging_group},
        )

        document.tags.add(*relevant_tags)


def set_storage_path(
    sender,
    document: Document,
    logging_group=None,
    classifier: DocumentClassifier | None = None,
    replace=False,
    use_first=True,
    suggest=False,
    base_url=None,
    stdout=None,
    style_func=None,
    **kwargs,
):
    if document.storage_path and not replace:
        return

    potential_storage_path = matching.match_storage_paths(
        document,
        classifier,
    )

    potential_count = len(potential_storage_path)
    selected = potential_storage_path[0] if potential_storage_path else None

    if potential_count > 1:
        if use_first:
            logger.info(
                f"Detected {potential_count} potential storage paths, "
                f"so we've opted for {selected}",
                extra={"group": logging_group},
            )
        else:
            logger.info(
                f"Detected {potential_count} potential storage paths, "
                f"not assigning any storage directory",
                extra={"group": logging_group},
            )
            return

    if selected or replace:
        if suggest:
            _suggestion_printer(
                stdout,
                style_func,
                "storage directory",
                document,
                selected,
                base_url,
            )
        else:
            logger.info(
                f"Assigning storage path {selected} to {document}",
                extra={"group": logging_group},
            )

            document.storage_path = selected
            document.save(update_fields=("storage_path",))


# see empty_trash in documents/tasks.py for signal handling
def cleanup_document_deletion(sender, instance, **kwargs):
    with FileLock(settings.MEDIA_LOCK):
        if settings.EMPTY_TRASH_DIR:
            # Find a non-conflicting filename in case a document with the same
            # name was moved to trash earlier
            counter = 0
            old_filename = os.path.split(instance.source_path)[1]
            (old_filebase, old_fileext) = os.path.splitext(old_filename)

            while True:
                new_file_path = os.path.join(
                    settings.EMPTY_TRASH_DIR,
                    old_filebase + (f"_{counter:02}" if counter else "") + old_fileext,
                )

                if os.path.exists(new_file_path):
                    counter += 1
                else:
                    break

            logger.debug(f"Moving {instance.source_path} to trash at {new_file_path}")
            try:
                shutil.move(instance.source_path, new_file_path)
            except OSError as e:
                logger.error(
                    f"Failed to move {instance.source_path} to trash at "
                    f"{new_file_path}: {e}. Skipping cleanup!",
                )
                return

        for filename in (
            instance.source_path,
            instance.archive_path,
            instance.thumbnail_path,
        ):
            if filename and os.path.isfile(filename):
                try:
                    os.unlink(filename)
                    logger.debug(f"Deleted file {filename}.")
                except OSError as e:
                    logger.warning(
                        f"While deleting document {instance!s}, the file "
                        f"{filename} could not be deleted: {e}",
                    )
            elif filename and not os.path.isfile(filename):
                logger.warning(f"Expected {filename} tp exist, but it did not")

        delete_empty_directories(
            os.path.dirname(instance.source_path),
            root=settings.ORIGINALS_DIR,
        )

        if instance.has_archive_version:
            delete_empty_directories(
                os.path.dirname(instance.archive_path),
                root=settings.ARCHIVE_DIR,
            )


class CannotMoveFilesException(Exception):
    pass


# should be disabled in /src/documents/management/commands/document_importer.py handle
@receiver(models.signals.post_save, sender=CustomFieldInstance)
@receiver(models.signals.m2m_changed, sender=Document.tags.through)
@receiver(models.signals.post_save, sender=Document)
def update_filename_and_move_files(
    sender,
    instance: Document | CustomFieldInstance,
    **kwargs,
):
    if isinstance(instance, CustomFieldInstance):
        instance = instance.document

    def validate_move(instance, old_path, new_path):
        if not os.path.isfile(old_path):
            # Can't do anything if the old file does not exist anymore.
            msg = f"Document {instance!s}: File {old_path} doesn't exist."
            logger.fatal(msg)
            raise CannotMoveFilesException(msg)

        if os.path.isfile(new_path):
            # Can't do anything if the new file already exists. Skip updating file.
            msg = f"Document {instance!s}: Cannot rename file since target path {new_path} already exists."
            logger.warning(msg)
            raise CannotMoveFilesException(msg)

    if not instance.filename:
        # Can't update the filename if there is no filename to begin with
        # This happens when the consumer creates a new document.
        # The document is modified and saved multiple times, and only after
        # everything is done (i.e., the generated filename is final),
        # filename will be set to the location where the consumer has put
        # the file.
        #
        # This will in turn cause this logic to move the file where it belongs.
        return

    with FileLock(settings.MEDIA_LOCK):
        try:
            # If this was waiting for the lock, the filename or archive_filename
            # of this document may have been updated.  This happens if multiple updates
            # get queued from the UI for the same document
            # So freshen up the data before doing anything
            instance.refresh_from_db()

            old_filename = instance.filename
            old_source_path = instance.source_path

            instance.filename = generate_unique_filename(instance)
            move_original = old_filename != instance.filename

            old_archive_filename = instance.archive_filename
            old_archive_path = instance.archive_path

            if instance.has_archive_version:
                instance.archive_filename = generate_unique_filename(
                    instance,
                    archive_filename=True,
                )

                move_archive = old_archive_filename != instance.archive_filename
            else:
                move_archive = False

            if not move_original and not move_archive:
                # Just update modified. Also, don't save() here to prevent infinite recursion.
                Document.objects.filter(pk=instance.pk).update(
                    modified=timezone.now(),
                )
                return

            if move_original:
                validate_move(instance, old_source_path, instance.source_path)
                create_source_path_directory(instance.source_path)
                shutil.move(old_source_path, instance.source_path)

            if move_archive:
                validate_move(instance, old_archive_path, instance.archive_path)
                create_source_path_directory(instance.archive_path)
                shutil.move(old_archive_path, instance.archive_path)

            # Don't save() here to prevent infinite recursion.
            Document.global_objects.filter(pk=instance.pk).update(
                filename=instance.filename,
                archive_filename=instance.archive_filename,
                modified=timezone.now(),
            )
            # Clear any caching for this document.  Slightly overkill, but not terrible
            clear_document_caches(instance.pk)

        except (OSError, DatabaseError, CannotMoveFilesException) as e:
            logger.warning(f"Exception during file handling: {e}")
            # This happens when either:
            #  - moving the files failed due to file system errors
            #  - saving to the database failed due to database errors
            # In both cases, we need to revert to the original state.

            # Try to move files to their original location.
            try:
                if move_original and os.path.isfile(instance.source_path):
                    logger.info("Restoring previous original path")
                    shutil.move(instance.source_path, old_source_path)

                if move_archive and os.path.isfile(instance.archive_path):
                    logger.info("Restoring previous archive path")
                    shutil.move(instance.archive_path, old_archive_path)

            except Exception:
                # This is fine, since:
                # A: if we managed to move source from A to B, we will also
                #  manage to move it from B to A. If not, we have a serious
                #  issue that's going to get caught by the santiy checker.
                #  All files remain in place and will never be overwritten,
                #  so this is not the end of the world.
                # B: if moving the original file failed, nothing has changed
                #  anyway.
                pass

            # restore old values on the instance
            instance.filename = old_filename
            instance.archive_filename = old_archive_filename

        # finally, remove any empty sub folders. This will do nothing if
        # something has failed above.
        if not os.path.isfile(old_source_path):
            delete_empty_directories(
                os.path.dirname(old_source_path),
                root=settings.ORIGINALS_DIR,
            )

        if instance.has_archive_version and not os.path.isfile(
            old_archive_path,
        ):
            delete_empty_directories(
                os.path.dirname(old_archive_path),
                root=settings.ARCHIVE_DIR,
            )


# should be disabled in /src/documents/management/commands/document_importer.py handle
@receiver(models.signals.post_save, sender=CustomField)
def check_paths_and_prune_custom_fields(sender, instance: CustomField, **kwargs):
    """
    When a custom field is updated:
    1. 'Select' custom field instances get their end-user value (e.g. in file names) from the select_options in extra_data,
    which is contained in the custom field itself. So when the field is changed, we (may) need to update the file names
    of all documents that have this custom field.
    2. If a 'Select' field option was removed, we need to nullify the custom field instances that have the option.
    """
    if (
        instance.data_type == CustomField.FieldDataType.SELECT
    ):  # Only select fields, for now
        for cf_instance in instance.fields.all():
            options = instance.extra_data.get("select_options", [])
            try:
                next(
                    option["label"]
                    for option in options
                    if option["id"] == cf_instance.value
                )
            except StopIteration:
                # The value of this custom field instance is not in the select options anymore
                cf_instance.value_select = None
                cf_instance.save()
            update_filename_and_move_files(sender, cf_instance)


def add_to_index(sender, document, **kwargs):
    from documents import index

    index.add_or_update_document(document)


def run_workflows_added(
    sender,
    document: Document,
    logging_group=None,
    original_file=None,
    **kwargs,
):
    run_workflows(
        trigger_type=WorkflowTrigger.WorkflowTriggerType.DOCUMENT_ADDED,
        document=document,
        logging_group=logging_group,
        overrides=None,
        original_file=original_file,
    )


def run_workflows_updated(sender, document: Document, logging_group=None, **kwargs):
    run_workflows(
        trigger_type=WorkflowTrigger.WorkflowTriggerType.DOCUMENT_UPDATED,
        document=document,
        logging_group=logging_group,
    )


@shared_task(
    retry_backoff=True,
    autoretry_for=(httpx.HTTPStatusError,),
    max_retries=3,
    throws=(httpx.HTTPError,),
)
def send_webhook(
    url: str,
    data: str | dict,
    headers: dict,
    files: dict,
    *,
    as_json: bool = False,
):
    try:
        if as_json:
            httpx.post(
                url,
                json=data,
                files=files,
                headers=headers,
            ).raise_for_status()
        else:
            httpx.post(
                url,
                data=data,
                files=files,
                headers=headers,
            ).raise_for_status()
        logger.info(
            f"Webhook sent to {url}",
        )
    except Exception as e:
        logger.error(
            f"Failed attempt sending webhook to {url}: {e}",
        )
        raise e


def run_workflows(
    trigger_type: WorkflowTrigger.WorkflowTriggerType,
    document: Document | ConsumableDocument,
    logging_group=None,
    overrides: DocumentMetadataOverrides | None = None,
    original_file: Path | None = None,
) -> tuple[DocumentMetadataOverrides, str] | None:
    """Run workflows which match a Document (or ConsumableDocument) for a specific trigger type.

    Assignment or removal actions are either applied directly to the document or an overrides object. If an overrides
    object is provided, the function returns the object with the applied changes or None if no actions were applied and a string
    of messages for each action. If no overrides object is provided, the changes are applied directly to the document and the
    function returns None.
    """

    def assignment_action():
        if action.assign_tags.exists():
            if not use_overrides:
                doc_tag_ids.extend(action.assign_tags.values_list("pk", flat=True))
            else:
                if overrides.tag_ids is None:
                    overrides.tag_ids = []
                overrides.tag_ids.extend(
                    action.assign_tags.values_list("pk", flat=True),
                )

        if action.assign_correspondent:
            if not use_overrides:
                document.correspondent = action.assign_correspondent
            else:
                overrides.correspondent_id = action.assign_correspondent.pk

        if action.assign_document_type:
            if not use_overrides:
                document.document_type = action.assign_document_type
            else:
                overrides.document_type_id = action.assign_document_type.pk

        if action.assign_storage_path:
            if not use_overrides:
                document.storage_path = action.assign_storage_path
            else:
                overrides.storage_path_id = action.assign_storage_path.pk

        if action.assign_owner:
            if not use_overrides:
                document.owner = action.assign_owner
            else:
                overrides.owner_id = action.assign_owner.pk

        if action.assign_title:
            if not use_overrides:
                try:
                    document.title = parse_w_workflow_placeholders(
                        action.assign_title,
                        document.correspondent.name if document.correspondent else "",
                        document.document_type.name if document.document_type else "",
                        document.owner.username if document.owner else "",
                        timezone.localtime(document.added),
                        document.original_filename or "",
                        document.filename or "",
                        timezone.localtime(document.created),
                    )
                except Exception:
                    logger.exception(
                        f"Error occurred parsing title assignment '{action.assign_title}', falling back to original",
                        extra={"group": logging_group},
                    )
            else:
                overrides.title = action.assign_title

        if any(
            [
                action.assign_view_users.exists(),
                action.assign_view_groups.exists(),
                action.assign_change_users.exists(),
                action.assign_change_groups.exists(),
            ],
        ):
            permissions = {
                "view": {
                    "users": action.assign_view_users.values_list("id", flat=True),
                    "groups": action.assign_view_groups.values_list("id", flat=True),
                },
                "change": {
                    "users": action.assign_change_users.values_list("id", flat=True),
                    "groups": action.assign_change_groups.values_list("id", flat=True),
                },
            }
            if not use_overrides:
                set_permissions_for_object(
                    permissions=permissions,
                    object=document,
                    merge=True,
                )
            else:
                overrides.view_users = list(
                    set(
                        (overrides.view_users or [])
                        + list(permissions["view"]["users"]),
                    ),
                )
                overrides.view_groups = list(
                    set(
                        (overrides.view_groups or [])
                        + list(permissions["view"]["groups"]),
                    ),
                )
                overrides.change_users = list(
                    set(
                        (overrides.change_users or [])
                        + list(permissions["change"]["users"]),
                    ),
                )
                overrides.change_groups = list(
                    set(
                        (overrides.change_groups or [])
                        + list(permissions["change"]["groups"]),
                    ),
                )

        if action.assign_custom_fields.exists():
            if not use_overrides:
                for field in action.assign_custom_fields.all():
                    if not CustomFieldInstance.objects.filter(
                        field=field,
                        document=document,
                    ).exists():
                        # can be triggered on existing docs, so only add the field if it doesn't already exist
                        CustomFieldInstance.objects.create(
                            field=field,
                            document=document,
                        )
            else:
                overrides.custom_field_ids = list(
                    set(
                        (overrides.custom_field_ids or [])
                        + list(
                            action.assign_custom_fields.values_list("pk", flat=True),
                        ),
                    ),
                )

    def removal_action():
        if action.remove_all_tags:
            if not use_overrides:
                doc_tag_ids.clear()
            else:
                overrides.tag_ids = None
        else:
            if not use_overrides:
                for tag in action.remove_tags.filter(
                    pk__in=document.tags.values_list("pk", flat=True),
                ):
                    doc_tag_ids.remove(tag.pk)
            elif overrides.tag_ids:
                for tag in action.remove_tags.filter(pk__in=overrides.tag_ids):
                    overrides.tag_ids.remove(tag.pk)

        if not use_overrides and (
            action.remove_all_correspondents
            or (
                document.correspondent
                and action.remove_correspondents.filter(
                    pk=document.correspondent.pk,
                ).exists()
            )
        ):
            document.correspondent = None
        elif use_overrides and (
            action.remove_all_correspondents
            or (
                overrides.correspondent_id
                and action.remove_correspondents.filter(
                    pk=overrides.correspondent_id,
                ).exists()
            )
        ):
            overrides.correspondent_id = None

        if not use_overrides and (
            action.remove_all_document_types
            or (
                document.document_type
                and action.remove_document_types.filter(
                    pk=document.document_type.pk,
                ).exists()
            )
        ):
            document.document_type = None
        elif use_overrides and (
            action.remove_all_document_types
            or (
                overrides.document_type_id
                and action.remove_document_types.filter(
                    pk=overrides.document_type_id,
                ).exists()
            )
        ):
            overrides.document_type_id = None

        if not use_overrides and (
            action.remove_all_storage_paths
            or (
                document.storage_path
                and action.remove_storage_paths.filter(
                    pk=document.storage_path.pk,
                ).exists()
            )
        ):
            document.storage_path = None
        elif use_overrides and (
            action.remove_all_storage_paths
            or (
                overrides.storage_path_id
                and action.remove_storage_paths.filter(
                    pk=overrides.storage_path_id,
                ).exists()
            )
        ):
            overrides.storage_path_id = None

        if not use_overrides and (
            action.remove_all_owners
            or (
                document.owner
                and action.remove_owners.filter(pk=document.owner.pk).exists()
            )
        ):
            document.owner = None
        elif use_overrides and (
            action.remove_all_owners
            or (
                overrides.owner_id
                and action.remove_owners.filter(pk=overrides.owner_id).exists()
            )
        ):
            overrides.owner_id = None

        if action.remove_all_permissions:
            if not use_overrides:
                permissions = {
                    "view": {"users": [], "groups": []},
                    "change": {"users": [], "groups": []},
                }
                set_permissions_for_object(
                    permissions=permissions,
                    object=document,
                    merge=False,
                )
            else:
                overrides.view_users = None
                overrides.view_groups = None
                overrides.change_users = None
                overrides.change_groups = None
        elif any(
            [
                action.remove_view_users.exists(),
                action.remove_view_groups.exists(),
                action.remove_change_users.exists(),
                action.remove_change_groups.exists(),
            ],
        ):
            if not use_overrides:
                for user in action.remove_view_users.all():
                    remove_perm("view_document", user, document)
                for user in action.remove_change_users.all():
                    remove_perm("change_document", user, document)
                for group in action.remove_view_groups.all():
                    remove_perm("view_document", group, document)
                for group in action.remove_change_groups.all():
                    remove_perm("change_document", group, document)
            else:
                if overrides.view_users:
                    for user in action.remove_view_users.filter(
                        pk__in=overrides.view_users,
                    ):
                        overrides.view_users.remove(user.pk)
                if overrides.change_users:
                    for user in action.remove_change_users.filter(
                        pk__in=overrides.change_users,
                    ):
                        overrides.change_users.remove(user.pk)
                if overrides.view_groups:
                    for group in action.remove_view_groups.filter(
                        pk__in=overrides.view_groups,
                    ):
                        overrides.view_groups.remove(group.pk)
                if overrides.change_groups:
                    for group in action.remove_change_groups.filter(
                        pk__in=overrides.change_groups,
                    ):
                        overrides.change_groups.remove(group.pk)

        if action.remove_all_custom_fields:
            if not use_overrides:
                CustomFieldInstance.objects.filter(document=document).delete()
            else:
                overrides.custom_field_ids = None
        elif action.remove_custom_fields.exists():
            if not use_overrides:
                CustomFieldInstance.objects.filter(
                    field__in=action.remove_custom_fields.all(),
                    document=document,
                ).delete()
            elif overrides.custom_field_ids:
                for field in action.remove_custom_fields.filter(
                    pk__in=overrides.custom_field_ids,
                ):
                    overrides.custom_field_ids.remove(field.pk)

    def email_action():
        if not settings.EMAIL_ENABLED:
            logger.error(
                "Email backend has not been configured, cannot send email notifications",
                extra={"group": logging_group},
            )
            return

        if not use_overrides:
            title = document.title
            doc_url = f"{settings.PAPERLESS_URL}/documents/{document.pk}/"
            correspondent = (
                document.correspondent.name if document.correspondent else ""
            )
            document_type = (
                document.document_type.name if document.document_type else ""
            )
            owner_username = document.owner.username if document.owner else ""
            filename = document.original_filename or ""
            current_filename = document.filename or ""
            added = timezone.localtime(document.added)
            created = timezone.localtime(document.created)
        else:
            title = overrides.title if overrides.title else str(document.original_file)
            doc_url = ""
            correspondent = (
                Correspondent.objects.filter(pk=overrides.correspondent_id).first()
                if overrides.correspondent_id
                else ""
            )
            document_type = (
                DocumentType.objects.filter(pk=overrides.document_type_id).first().name
                if overrides.document_type_id
                else ""
            )
            owner_username = (
                User.objects.filter(pk=overrides.owner_id).first().username
                if overrides.owner_id
                else ""
            )
            filename = document.original_file if document.original_file else ""
            current_filename = filename
            added = timezone.localtime(timezone.now())
            created = timezone.localtime(overrides.created)

        subject = parse_w_workflow_placeholders(
            action.email.subject,
            correspondent,
            document_type,
            owner_username,
            added,
            filename,
            current_filename,
            created,
            title,
            doc_url,
        )
        body = parse_w_workflow_placeholders(
            action.email.body,
            correspondent,
            document_type,
            owner_username,
            added,
            filename,
            current_filename,
            created,
            title,
            doc_url,
        )
        try:
            n_messages = send_email(
                subject=subject,
                body=body,
                to=action.email.to.split(","),
                attachment=original_file if action.email.include_document else None,
                attachment_mime_type=document.mime_type,
            )
            logger.debug(
                f"Sent {n_messages} notification email(s) to {action.email.to}",
                extra={"group": logging_group},
            )
        except Exception as e:
            logger.exception(
                f"Error occurred sending notification email: {e}",
                extra={"group": logging_group},
            )

    def webhook_action():
        if not use_overrides:
            title = document.title
            doc_url = f"{settings.PAPERLESS_URL}/documents/{document.pk}/"
            correspondent = (
                document.correspondent.name if document.correspondent else ""
            )
            document_type = (
                document.document_type.name if document.document_type else ""
            )
            owner_username = document.owner.username if document.owner else ""
            filename = document.original_filename or ""
            current_filename = document.filename or ""
            added = timezone.localtime(document.added)
            created = timezone.localtime(document.created)
        else:
            title = overrides.title if overrides.title else str(document.original_file)
            doc_url = ""
            correspondent = (
                Correspondent.objects.filter(pk=overrides.correspondent_id).first()
                if overrides.correspondent_id
                else ""
            )
            document_type = (
                DocumentType.objects.filter(pk=overrides.document_type_id).first().name
                if overrides.document_type_id
                else ""
            )
            owner_username = (
                User.objects.filter(pk=overrides.owner_id).first().username
                if overrides.owner_id
                else ""
            )
            filename = document.original_file if document.original_file else ""
            current_filename = filename
            added = timezone.localtime(timezone.now())
            created = timezone.localtime(overrides.created)

        try:
            data = {}
            if action.webhook.use_params:
                if action.webhook.params:
                    try:
                        for key, value in action.webhook.params.items():
                            data[key] = parse_w_workflow_placeholders(
                                value,
                                correspondent,
                                document_type,
                                owner_username,
                                added,
                                filename,
                                current_filename,
                                created,
                                title,
                                doc_url,
                            )
                    except Exception as e:
                        logger.error(
                            f"Error occurred parsing webhook params: {e}",
                            extra={"group": logging_group},
                        )
            else:
                data = parse_w_workflow_placeholders(
                    action.webhook.body,
                    correspondent,
                    document_type,
                    owner_username,
                    added,
                    filename,
                    current_filename,
                    created,
                    title,
                    doc_url,
                )
            headers = {}
            if action.webhook.headers:
                try:
                    headers = {
                        str(k): str(v) for k, v in action.webhook.headers.items()
                    }
                except Exception as e:
                    logger.error(
                        f"Error occurred parsing webhook headers: {e}",
                        extra={"group": logging_group},
                    )
            files = None
            if action.webhook.include_document:
                with open(
                    original_file,
                    "rb",
                ) as f:
                    files = {
                        "file": (
                            document.original_filename,
                            f.read(),
                            document.mime_type,
                        ),
                    }
            send_webhook.delay(
                url=action.webhook.url,
                data=data,
                headers=headers,
                files=files,
                as_json=action.webhook.as_json,
            )
            logger.debug(
                f"Webhook to {action.webhook.url} queued",
                extra={"group": logging_group},
            )
        except Exception as e:
            logger.exception(
                f"Error occurred sending webhook: {e}",
                extra={"group": logging_group},
            )

    use_overrides = overrides is not None
    if original_file is None:
        original_file = (
            document.source_path if not use_overrides else document.original_file
        )
    messages = []

    workflows = (
        Workflow.objects.filter(enabled=True, triggers__type=trigger_type)
        .prefetch_related(
            "actions",
            "actions__assign_view_users",
            "actions__assign_view_groups",
            "actions__assign_change_users",
            "actions__assign_change_groups",
            "actions__assign_custom_fields",
            "actions__remove_tags",
            "actions__remove_correspondents",
            "actions__remove_document_types",
            "actions__remove_storage_paths",
            "actions__remove_custom_fields",
            "actions__remove_owners",
            "triggers",
        )
        .order_by("order")
        .distinct()
    )

    for workflow in workflows:
        if not use_overrides:
            # This can be called from bulk_update_documents, which may be running multiple times
            # Refresh this so the matching data is fresh and instance fields are re-freshed
            # Otherwise, this instance might be behind and overwrite the work another process did
            document.refresh_from_db()
            doc_tag_ids = list(document.tags.values_list("pk", flat=True))

        if matching.document_matches_workflow(document, workflow, trigger_type):
            action: WorkflowAction
            for action in workflow.actions.all():
                message = f"Applying {action} from {workflow}"
                if not use_overrides:
                    logger.info(message, extra={"group": logging_group})
                else:
                    messages.append(message)

                if action.type == WorkflowAction.WorkflowActionType.ASSIGNMENT:
                    assignment_action()
                elif action.type == WorkflowAction.WorkflowActionType.REMOVAL:
                    removal_action()
                elif action.type == WorkflowAction.WorkflowActionType.EMAIL:
                    email_action()
                elif action.type == WorkflowAction.WorkflowActionType.WEBHOOK:
                    webhook_action()

            if not use_overrides:
                # save first before setting tags
                document.save()
                document.tags.set(doc_tag_ids)

            WorkflowRun.objects.create(
                workflow=workflow,
                type=trigger_type,
                document=document if not use_overrides else None,
            )

    if use_overrides:
        return overrides, "\n".join(messages)


@before_task_publish.connect
def before_task_publish_handler(sender=None, headers=None, body=None, **kwargs):
    """
    Creates the PaperlessTask object in a pending state.  This is sent before
    the task reaches the broker, but before it begins executing on a worker.

    https://docs.celeryq.dev/en/stable/userguide/signals.html#before-task-publish

    https://docs.celeryq.dev/en/stable/internals/protocol.html#version-2

    """
    if "task" not in headers or headers["task"] != "documents.tasks.consume_file":
        # Assumption: this is only ever a v2 message
        return

    try:
        close_old_connections()

        task_args = body[0]
        input_doc, overrides = task_args

        task_file_name = input_doc.original_file.name
        user_id = overrides.owner_id if overrides else None

        PaperlessTask.objects.create(
            task_id=headers["id"],
            status=states.PENDING,
            task_file_name=task_file_name,
            task_name=headers["task"],
            result=None,
            date_created=timezone.now(),
            date_started=None,
            date_done=None,
            owner_id=user_id,
        )
    except Exception:  # pragma: no cover
        # Don't let an exception in the signal handlers prevent
        # a document from being consumed.
        logger.exception("Creating PaperlessTask failed")


@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, **kwargs):
    """

    Updates the PaperlessTask to be started.  Sent before the task begins execution
    on a worker.

    https://docs.celeryq.dev/en/stable/userguide/signals.html#task-prerun
    """
    try:
        close_old_connections()
        task_instance = PaperlessTask.objects.filter(task_id=task_id).first()

        if task_instance is not None:
            task_instance.status = states.STARTED
            task_instance.date_started = timezone.now()
            task_instance.save()
    except Exception:  # pragma: no cover
        # Don't let an exception in the signal handlers prevent
        # a document from being consumed.
        logger.exception("Setting PaperlessTask started failed")


@task_postrun.connect
def task_postrun_handler(
    sender=None,
    task_id=None,
    task=None,
    retval=None,
    state=None,
    **kwargs,
):
    """
    Updates the result of the PaperlessTask.

    https://docs.celeryq.dev/en/stable/userguide/signals.html#task-postrun
    """
    try:
        close_old_connections()
        task_instance = PaperlessTask.objects.filter(task_id=task_id).first()

        if task_instance is not None:
            task_instance.status = state
            task_instance.result = retval
            task_instance.date_done = timezone.now()
            task_instance.save()
    except Exception:  # pragma: no cover
        # Don't let an exception in the signal handlers prevent
        # a document from being consumed.
        logger.exception("Updating PaperlessTask failed")


@task_failure.connect
def task_failure_handler(
    sender=None,
    task_id=None,
    exception=None,
    args=None,
    traceback=None,
    **kwargs,
):
    """
    Updates the result of a failed PaperlessTask.

    https://docs.celeryq.dev/en/stable/userguide/signals.html#task-failure
    """
    try:
        close_old_connections()
        task_instance = PaperlessTask.objects.filter(task_id=task_id).first()

        if task_instance is not None and task_instance.result is None:
            task_instance.status = states.FAILURE
            task_instance.result = traceback
            task_instance.date_done = timezone.now()
            task_instance.save()
    except Exception:  # pragma: no cover
        logger.exception("Updating PaperlessTask failed")
