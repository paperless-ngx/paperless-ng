import logging
import multiprocessing
import shutil

import tqdm
from django import db
from django.core.management.base import BaseCommand

from documents.models import Document
from ...mixins import Renderable
from ...parsers import get_parser_class_for_mime_type


def _process_document(doc_in):
    document = Document.objects.get(id=doc_in)
    parser_class = get_parser_class_for_mime_type(document.mime_type)

    if parser_class:
        parser = parser_class(logging_group=None)
    else:
        print(f"{document} No parser for mime type {document.mime_type}")
        return

    try:
        thumb = parser.get_optimised_thumbnail(
            document.source_path, document.mime_type)

        shutil.move(thumb, document.thumbnail_path)
    finally:
        parser.cleanup()


class Command(Renderable, BaseCommand):

    help = """
        This will regenerate the thumbnails for all documents.
    """.replace("    ", "")

    def __init__(self, *args, **kwargs):
        self.verbosity = 0
        BaseCommand.__init__(self, *args, **kwargs)

    def add_arguments(self, parser):
        parser.add_argument(
            "-d", "--document",
            default=None,
            type=int,
            required=False,
            help="Specify the ID of a document, and this command will only "
                 "run on this specific document."
        )

    def handle(self, *args, **options):

        self.verbosity = options["verbosity"]

        logging.getLogger().handlers[0].level = logging.ERROR

        if options['document']:
            documents = Document.objects.filter(pk=options['document'])
        else:
            documents = Document.objects.all()

        ids = [doc.id for doc in documents]

        # Note to future self: this prevents django from reusing database
        # conncetions between processes, which is bad and does not work
        # with postgres.
        db.connections.close_all()

        with multiprocessing.Pool() as pool:
            list(tqdm.tqdm(
                pool.imap_unordered(_process_document, ids), total=len(ids)
            ))
