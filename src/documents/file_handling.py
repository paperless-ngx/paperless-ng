import os

from django.conf import settings

from documents.models import Document
from documents.templating.filepath import validate_filepath_template_and_render
from documents.templating.utils import convert_format_str_to_template_format


def create_source_path_directory(source_path):
    os.makedirs(os.path.dirname(source_path), exist_ok=True)


def delete_empty_directories(directory, root):
    if not os.path.isdir(directory):
        return

    # Go up in the directory hierarchy and try to delete all directories
    directory = os.path.normpath(directory)
    root = os.path.normpath(root)

    if not directory.startswith(root + os.path.sep):
        # don't do anything outside our originals folder.

        # append os.path.set so that we avoid these cases:
        #   directory = /home/originals2/test
        #   root = /home/originals ("/" gets appended and startswith fails)
        return

    while directory != root:
        if not os.listdir(directory):
            # it's empty
            try:
                os.rmdir(directory)
            except OSError:
                # whatever. empty directories aren't that bad anyway.
                return
        else:
            # it's not empty.
            return

        # go one level up
        directory = os.path.normpath(os.path.dirname(directory))


def generate_unique_filename(doc, *, archive_filename=False):
    """
    Generates a unique filename for doc in settings.ORIGINALS_DIR.

    The returned filename is guaranteed to be either the current filename
    of the document if unchanged, or a new filename that does not correspondent
    to any existing files. The function will append _01, _02, etc to the
    filename before the extension to avoid conflicts.

    If archive_filename is True, return a unique archive filename instead.

    """
    if archive_filename:
        old_filename = doc.archive_filename
        root = settings.ARCHIVE_DIR
    else:
        old_filename = doc.filename
        root = settings.ORIGINALS_DIR

    # If generating archive filenames, try to make a name that is similar to
    # the original filename first.

    if archive_filename and doc.filename:
        new_filename = os.path.splitext(doc.filename)[0] + ".pdf"
        if new_filename == old_filename or not os.path.exists(
            os.path.join(root, new_filename),
        ):
            return new_filename

    counter = 0

    while True:
        new_filename = generate_filename(
            doc,
            counter=counter,
            archive_filename=archive_filename,
        )
        if new_filename == old_filename:
            # still the same as before.
            return new_filename

        if os.path.exists(os.path.join(root, new_filename)):
            counter += 1
        else:
            return new_filename


def generate_filename(
    doc: Document,
    *,
    counter=0,
    append_gpg=True,
    archive_filename=False,
):
    path = ""

    def format_filename(document: Document, template_str: str) -> str | None:
        rendered_filename = validate_filepath_template_and_render(
            template_str,
            document,
        )
        if rendered_filename is None:
            return None

        # Apply this setting.  It could become a filter in the future (or users could use |default)
        if settings.FILENAME_FORMAT_REMOVE_NONE:
            rendered_filename = rendered_filename.replace("/-none-/", "/")
            rendered_filename = rendered_filename.replace(" -none-", "")
            rendered_filename = rendered_filename.replace("-none-", "")
            rendered_filename = rendered_filename.strip(os.sep)

        rendered_filename = rendered_filename.replace(
            "-none-",
            "none",
        )  # backward compatibility

        return rendered_filename

    # Determine the source of the format string
    if doc.storage_path is not None:
        filename_format = doc.storage_path.path
    elif settings.FILENAME_FORMAT is not None:
        # Maybe convert old to new style
        filename_format = convert_format_str_to_template_format(
            settings.FILENAME_FORMAT,
        )
    else:
        filename_format = None

    # If we have one, render it
    if filename_format is not None:
        path = format_filename(doc, filename_format)

    counter_str = f"_{counter:02}" if counter else ""
    filetype_str = ".pdf" if archive_filename else doc.file_type

    if path:
        filename = f"{path}{counter_str}{filetype_str}"
    else:
        filename = f"{doc.pk:07}{counter_str}{filetype_str}"

    if append_gpg and doc.storage_type == doc.STORAGE_TYPE_GPG:
        filename += ".gpg"

    return filename
