import logging
import os
from subprocess import Popen

from django.conf import settings
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import models, DatabaseError
from django.db.models import Q
from django.dispatch import receiver
from django.utils import timezone
from filelock import FileLock

from .. import index, matching
from ..file_handling import delete_empty_directories, \
    create_source_path_directory, \
    generate_unique_filename
from ..models import Document, Tag


logger = logging.getLogger("paperless.handlers")


def add_inbox_tags(sender, document=None, logging_group=None, **kwargs):
    inbox_tags = Tag.objects.filter(is_inbox_tag=True)
    document.tags.add(*inbox_tags)


def set_correspondent(sender,
                      document=None,
                      logging_group=None,
                      classifier=None,
                      replace=False,
                      use_first=True,
                      **kwargs):
    if document.correspondent and not replace:
        return

    potential_correspondents = matching.match_correspondents(document,
                                                             classifier)

    potential_count = len(potential_correspondents)
    if potential_correspondents:
        selected = potential_correspondents[0]
    else:
        selected = None
    if potential_count > 1:
        if use_first:
            logger.info(
                f"Detected {potential_count} potential correspondents, "
                f"so we've opted for {selected}",
                extra={'group': logging_group}
            )
        else:
            logger.info(
                f"Detected {potential_count} potential correspondents, "
                f"not assigning any correspondent",
                extra={'group': logging_group}
            )
            return

    if selected or replace:
        logger.info(
            f"Assigning correspondent {selected} to {document}",
            extra={'group': logging_group}
        )

        document.correspondent = selected
        document.save(update_fields=("correspondent",))


def set_document_type(sender,
                      document=None,
                      logging_group=None,
                      classifier=None,
                      replace=False,
                      use_first=True,
                      **kwargs):
    if document.document_type and not replace:
        return

    potential_document_type = matching.match_document_types(document,
                                                            classifier)

    potential_count = len(potential_document_type)
    if potential_document_type:
        selected = potential_document_type[0]
    else:
        selected = None

    if potential_count > 1:
        if use_first:
            logger.info(
                f"Detected {potential_count} potential document types, "
                f"so we've opted for {selected}",
                extra={'group': logging_group}
            )
        else:
            logger.info(
                f"Detected {potential_count} potential document types, "
                f"not assigning any document type",
                extra={'group': logging_group}
            )
            return

    if selected or replace:
        logger.info(
            f"Assigning document type {selected} to {document}",
            extra={'group': logging_group}
        )

        document.document_type = selected
        document.save(update_fields=("document_type",))


def set_tags(sender,
             document=None,
             logging_group=None,
             classifier=None,
             replace=False,
             **kwargs):

    if replace:
        Document.tags.through.objects.filter(document=document).exclude(
            Q(tag__is_inbox_tag=True)).exclude(
            Q(tag__match="") & ~Q(tag__matching_algorithm=Tag.MATCH_AUTO)
        ).delete()

    current_tags = set(document.tags.all())

    matched_tags = matching.match_tags(document, classifier)

    relevant_tags = set(matched_tags) - current_tags

    if not relevant_tags:
        return

    message = 'Tagging "{}" with "{}"'
    logger.info(
        message.format(document, ", ".join([t.name for t in relevant_tags])),
        extra={'group': logging_group}
    )

    document.tags.add(*relevant_tags)


@receiver(models.signals.post_delete, sender=Document)
def cleanup_document_deletion(sender, instance, using, **kwargs):
    with FileLock(settings.MEDIA_LOCK):
        for filename in (instance.source_path,
                         instance.archive_path,
                         instance.thumbnail_path):
            if filename and os.path.isfile(filename):
                try:
                    os.unlink(filename)
                    logger.debug(
                        f"Deleted file {filename}.")
                except OSError as e:
                    logger.warning(
                        f"While deleting document {str(instance)}, the file "
                        f"{filename} could not be deleted: {e}"
                    )

        delete_empty_directories(
            os.path.dirname(instance.source_path),
            root=settings.ORIGINALS_DIR
        )

        if instance.has_archive_version:
            delete_empty_directories(
                os.path.dirname(instance.archive_path),
                root=settings.ARCHIVE_DIR
            )


def validate_move(instance, old_path, new_path):
    if not os.path.isfile(old_path):
        # Can't do anything if the old file does not exist anymore.
        logger.fatal(
            f"Document {str(instance)}: File {old_path} has gone.")
        return False

    if os.path.isfile(new_path):
        # Can't do anything if the new file already exists. Skip updating file.
        logger.warning(
            f"Document {str(instance)}: Cannot rename file "
            f"since target path {new_path} already exists.")
        return False

    return True


@receiver(models.signals.m2m_changed, sender=Document.tags.through)
@receiver(models.signals.post_save, sender=Document)
def update_filename_and_move_files(sender, instance, **kwargs):

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
        old_filename = instance.filename
        new_filename = generate_unique_filename(instance)

        if new_filename == instance.filename:
            # Don't do anything if its the same.
            return

        old_source_path = instance.source_path
        new_source_path = os.path.join(settings.ORIGINALS_DIR, new_filename)

        if not validate_move(instance, old_source_path, new_source_path):
            return

        # archive files are optional, archive checksum tells us if we have one,
        # since this is None for documents without archived files.
        if instance.has_archive_version:
            old_archive_filename = instance.archive_filename
            new_archive_filename = generate_unique_filename(
                instance, archive_filename=True
            )
            old_archive_path = instance.archive_path
            new_archive_path = os.path.join(settings.ARCHIVE_DIR,
                                            new_archive_filename)

            if not validate_move(instance, old_archive_path, new_archive_path):
                return

            create_source_path_directory(new_archive_path)
        else:
            old_archive_filename = None
            new_archive_filename = None
            old_archive_path = None
            new_archive_path = None

        create_source_path_directory(new_source_path)

        try:
            os.rename(old_source_path, new_source_path)
            instance.filename = new_filename

            if instance.has_archive_version:
                os.rename(old_archive_path, new_archive_path)
                instance.archive_filename = new_archive_filename

            # Don't save() here to prevent infinite recursion.
            Document.objects.filter(pk=instance.pk).update(
                filename=instance.filename,
                archive_filename=instance.archive_filename,
            )

        except OSError as e:
            instance.filename = old_filename
            instance.archive_filename = old_archive_filename
            # this happens when we can't move a file. If that's the case for
            # the archive file, we try our best to revert the changes.
            # no need to save the instance, the update() has not happened yet.
            try:
                os.rename(new_source_path, old_source_path)
                if instance.has_archive_version:
                    os.rename(new_archive_path, old_archive_path)
            except Exception as e:
                # This is fine, since:
                # A: if we managed to move source from A to B, we will also
                #  manage to move it from B to A. If not, we have a serious
                #  issue that's going to get caught by the santiy checker.
                #  All files remain in place and will never be overwritten,
                #  so this is not the end of the world.
                # B: if moving the orignal file failed, nothing has changed
                #  anyway.
                pass
        except DatabaseError as e:
            # this happens after moving files, so move them back into place.
            # since moving them once succeeded, it's very likely going to
            # succeed again.
            os.rename(new_source_path, old_source_path)
            if instance.has_archive_version:
                os.rename(new_archive_path, old_archive_path)
            instance.filename = old_filename
            instance.archive_filename = old_archive_filename
            # again, no need to save the instance, since the actual update()
            # operation failed.

        # finally, remove any empty sub folders. This will do nothing if
        # something has failed above.
        if not os.path.isfile(old_source_path):
            delete_empty_directories(os.path.dirname(old_source_path),
                                     root=settings.ORIGINALS_DIR)

        if instance.has_archive_version and not os.path.isfile(old_archive_path):  # NOQA: E501
            delete_empty_directories(os.path.dirname(old_archive_path),
                                     root=settings.ARCHIVE_DIR)


def set_log_entry(sender, document=None, logging_group=None, **kwargs):

    ct = ContentType.objects.get(model="document")
    user = User.objects.get(username="consumer")

    LogEntry.objects.create(
        action_flag=ADDITION,
        action_time=timezone.now(),
        content_type=ct,
        object_id=document.pk,
        user=user,
        object_repr=document.__str__(),
    )


def add_to_index(sender, document, **kwargs):
    index.add_or_update_document(document)
