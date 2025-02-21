import logging
import multiprocessing

from django import db
from django.conf import settings
from django.core.management.base import BaseCommand
from rich.progress import track

from documents.management.commands.mixins import MultiProcessMixin
from documents.management.commands.mixins import ProgressBarMixin
from documents.models import Document
from documents.tasks import update_document_content_maybe_archive_file

logger = logging.getLogger("paperless.management.archiver")


class Command(MultiProcessMixin, ProgressBarMixin, BaseCommand):
    help = (
        "Using the current classification model, assigns correspondents, tags "
        "and document types to all documents, effectively allowing you to "
        "back-tag all previously indexed documents with metadata created (or "
        "modified) after their initial import."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-f",
            "--overwrite",
            default=False,
            action="store_true",
            help=(
                "Recreates the archived document for documents that already "
                "have an archived version."
            ),
        )
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
        self.handle_processes_mixin(**options)
        self.handle_progress_bar_mixin(**options)

        settings.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

        overwrite = options["overwrite"]

        if options["document"]:
            documents = Document.objects.filter(pk=options["document"])
        else:
            documents = Document.objects.all()

        document_ids = list(
            map(
                lambda doc: doc.id,
                filter(lambda d: overwrite or not d.has_archive_version, documents),
            ),
        )

        # Note to future self: this prevents django from reusing database
        # connections between processes, which is bad and does not work
        # with postgres.
        db.connections.close_all()

        try:
            logging.getLogger().handlers[0].level = logging.ERROR

            if self.process_count == 1:
                for doc_id in document_ids:
                    update_document_content_maybe_archive_file(doc_id)
            else:  # pragma: no cover
                with multiprocessing.Pool(self.process_count) as pool:
                    list(
                        track(
                            pool.imap_unordered(
                                update_document_content_maybe_archive_file,
                                document_ids,
                            ),
                            total=len(document_ids),
                            disable=self.no_progress_bar,
                        ),
                    )
        except KeyboardInterrupt:
            self.stdout.write(self.style.NOTICE("Aborting..."))
