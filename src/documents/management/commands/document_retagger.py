import logging

from django.core.management.base import BaseCommand

from documents.classifier import DocumentClassifier
from documents.models import Document
from ...mixins import Renderable
from ...signals.handlers import set_correspondent, set_document_type, set_tags


class Command(Renderable, BaseCommand):

    help = """
        Using the current classification model, assigns correspondents, tags
        and document types to all documents, effectively allowing you to
        back-tag all previously indexed documents with metadata created (or
        modified) after their initial import.
    """.replace("    ", "")

    def __init__(self, *args, **kwargs):
        self.verbosity = 0
        BaseCommand.__init__(self, *args, **kwargs)

    def add_arguments(self, parser):
        parser.add_argument(
            "-c", "--correspondent",
            default=False,
            action="store_true"
        )
        parser.add_argument(
            "-T", "--tags",
            default=False,
            action="store_true"
        )
        parser.add_argument(
            "-t", "--document_type",
            default=False,
            action="store_true"
        )
        parser.add_argument(
            "-i", "--inbox-only",
            default=False,
            action="store_true"
        )
        parser.add_argument(
            "--use-first",
            default=False,
            action="store_true",
            help="By default this command won't try to assign a correspondent "
                 "if more than one matches the document.  Use this flag if "
                 "you'd rather it just pick the first one it finds."
        )
        parser.add_argument(
            "-f", "--overwrite",
            default=False,
            action="store_true",
            help="If set, the document retagger will overwrite any previously"
                 "set correspondent, document and remove correspondents, types"
                 "and tags that do not match anymore due to changed rules."
        )

    def handle(self, *args, **options):

        self.verbosity = options["verbosity"]

        if options["inbox_only"]:
            queryset = Document.objects.filter(tags__is_inbox_tag=True)
        else:
            queryset = Document.objects.all()
        documents = queryset.distinct()

        classifier = DocumentClassifier()
        try:
            classifier.reload()
        except FileNotFoundError:
            logging.getLogger(__name__).warning("Cannot classify documents, "
                                              "classifier model file was not "
                                              "found.")
            classifier = None

        for document in documents:
            logging.getLogger(__name__).info(
                "Processing document {}".format(document.title)
            )

            if options['correspondent']:
                set_correspondent(
                    sender=None,
                    document=document,
                    classifier=classifier,
                    replace=options['overwrite'],
                    use_first=options['use_first'])

            if options['document_type']:
                set_document_type(sender=None,
                                  document=document,
                                  classifier=classifier,
                                  replace=options['overwrite'],
                                  use_first=options['use_first'])

            if options['tags']:
                set_tags(
                    sender=None,
                    document=document,
                    classifier=classifier,
                    replace=options['overwrite'])
