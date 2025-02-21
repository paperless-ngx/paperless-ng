import logging
import multiprocessing
import shutil

from django import db
from django.core.management.base import BaseCommand
from rich.progress import track

from documents.management.commands.mixins import MultiProcessMixin
from documents.management.commands.mixins import ProgressBarMixin
from documents.models import Document
from documents.parsers import get_parser_class_for_mime_type


def _process_document(doc_id):
    document: Document = Document.objects.get(id=doc_id)
    parser_class = get_parser_class_for_mime_type(document.mime_type)

    if parser_class:
        parser = parser_class(logging_group=None)
    else:
        print(f"{document} No parser for mime type {document.mime_type}")  # noqa: T201
        return

    try:
        thumb = parser.get_thumbnail(
            document.source_path,
            document.mime_type,
            document.get_public_filename(),
        )

        shutil.move(thumb, document.thumbnail_path)
    finally:
        parser.cleanup()


class Command(MultiProcessMixin, ProgressBarMixin, BaseCommand):
    help = "This will regenerate the thumbnails for all documents."

    def add_arguments(self, parser):
        parser.add_argument(
            "-d",
            "--document",
            default=None,
            type=int,
            required=False,
            help=(
                "Specify the ID of a document, and this command will only "
                "run on this specific document."
            ),
        )
        self.add_argument_progress_bar_mixin(parser)
        self.add_argument_processes_mixin(parser)

    def handle(self, *args, **options):
        logging.getLogger().handlers[0].level = logging.ERROR

        self.handle_processes_mixin(**options)
        self.handle_progress_bar_mixin(**options)

        if options["document"]:
            documents = Document.objects.filter(pk=options["document"])
        else:
            documents = Document.objects.all()

        ids = [doc.id for doc in documents]

        # Note to future self: this prevents django from reusing database
        # connections between processes, which is bad and does not work
        # with postgres.
        db.connections.close_all()

        if self.process_count == 1:
            for doc_id in ids:
                _process_document(doc_id)
        else:  # pragma: no cover
            with multiprocessing.Pool(processes=self.process_count) as pool:
                list(
                    track(
                        pool.imap_unordered(_process_document, ids),
                        total=len(ids),
                        disable=self.no_progress_bar,
                    ),
                )
