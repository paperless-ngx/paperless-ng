import hashlib
import logging
from collections import defaultdict
from pathlib import Path
from typing import Final

from django.conf import settings
from tqdm import tqdm

from documents.models import Document


class SanityCheckMessages:
    def __init__(self):
        self._messages: dict[int, list[dict]] = defaultdict(list)
        self.has_error = False
        self.has_warning = False

    def error(self, doc_pk, message):
        self._messages[doc_pk].append({"level": logging.ERROR, "message": message})
        self.has_error = True

    def warning(self, doc_pk, message):
        self._messages[doc_pk].append({"level": logging.WARNING, "message": message})
        self.has_warning = True

    def info(self, doc_pk, message):
        self._messages[doc_pk].append({"level": logging.INFO, "message": message})

    def log_messages(self):
        logger = logging.getLogger("paperless.sanity_checker")

        if len(self._messages) == 0:
            logger.info("Sanity checker detected no issues.")
        else:
            # Query once
            all_docs = Document.global_objects.all()

            for doc_pk in self._messages:
                if doc_pk is not None:
                    doc = all_docs.get(pk=doc_pk)
                    logger.info(
                        f"Detected following issue(s) with document #{doc.pk},"
                        f" titled {doc.title}",
                    )
                for msg in self._messages[doc_pk]:
                    logger.log(msg["level"], msg["message"])

    def __len__(self):
        return len(self._messages)

    def __getitem__(self, item):
        return self._messages[item]


class SanityCheckFailedException(Exception):
    pass


def check_sanity(*, progress=False) -> SanityCheckMessages:
    messages = SanityCheckMessages()

    present_files = {
        x.resolve() for x in Path(settings.MEDIA_ROOT).glob("**/*") if not x.is_dir()
    }

    lockfile = Path(settings.MEDIA_LOCK).resolve()
    if lockfile in present_files:
        present_files.remove(lockfile)

    for doc in tqdm(Document.global_objects.all(), disable=not progress):
        # Check sanity of the thumbnail
        thumbnail_path: Final[Path] = Path(doc.thumbnail_path).resolve()
        if not thumbnail_path.exists() or not thumbnail_path.is_file():
            messages.error(doc.pk, "Thumbnail of document does not exist.")
        else:
            if thumbnail_path in present_files:
                present_files.remove(thumbnail_path)
            try:
                _ = thumbnail_path.read_bytes()
            except OSError as e:
                messages.error(doc.pk, f"Cannot read thumbnail file of document: {e}")

        # Check sanity of the original file
        # TODO: extract method
        source_path: Final[Path] = Path(doc.source_path).resolve()
        if not source_path.exists() or not source_path.is_file():
            messages.error(doc.pk, "Original of document does not exist.")
        else:
            if source_path in present_files:
                present_files.remove(source_path)
            try:
                checksum = hashlib.md5(source_path.read_bytes()).hexdigest()
            except OSError as e:
                messages.error(doc.pk, f"Cannot read original file of document: {e}")
            else:
                if checksum != doc.checksum:
                    messages.error(
                        doc.pk,
                        "Checksum mismatch. "
                        f"Stored: {doc.checksum}, actual: {checksum}.",
                    )

        # Check sanity of the archive file.
        if doc.archive_checksum is not None and doc.archive_filename is None:
            messages.error(
                doc.pk,
                "Document has an archive file checksum, but no archive filename.",
            )
        elif doc.archive_checksum is None and doc.archive_filename is not None:
            messages.error(
                doc.pk,
                "Document has an archive file, but its checksum is missing.",
            )
        elif doc.has_archive_version:
            archive_path: Final[Path] = Path(doc.archive_path).resolve()
            if not archive_path.exists() or not archive_path.is_file():
                messages.error(doc.pk, "Archived version of document does not exist.")
            else:
                if archive_path in present_files:
                    present_files.remove(archive_path)
                try:
                    checksum = hashlib.md5(archive_path.read_bytes()).hexdigest()
                except OSError as e:
                    messages.error(
                        doc.pk,
                        f"Cannot read archive file of document : {e}",
                    )
                else:
                    if checksum != doc.archive_checksum:
                        messages.error(
                            doc.pk,
                            "Checksum mismatch of archived document. "
                            f"Stored: {doc.archive_checksum}, "
                            f"actual: {checksum}.",
                        )

        # other document checks
        if not doc.content:
            messages.info(doc.pk, "Document contains no OCR data")

    for extra_file in present_files:
        messages.warning(None, f"Orphaned file in media dir: {extra_file}")

    return messages
