import logging

from django.core.management.base import BaseCommand
from rich.progress import track

from documents.classifier import load_classifier
from documents.management.commands.mixins import ProgressBarMixin
from documents.models import Document
from documents.signals.handlers import set_correspondent
from documents.signals.handlers import set_document_type
from documents.signals.handlers import set_storage_path
from documents.signals.handlers import set_tags

logger = logging.getLogger("paperless.management.retagger")


class Command(ProgressBarMixin, BaseCommand):
    help = (
        "Using the current classification model, assigns correspondents, tags "
        "and document types to all documents, effectively allowing you to "
        "back-tag all previously indexed documents with metadata created (or "
        "modified) after their initial import."
    )

    def add_arguments(self, parser):
        parser.add_argument("-c", "--correspondent", default=False, action="store_true")
        parser.add_argument("-T", "--tags", default=False, action="store_true")
        parser.add_argument("-t", "--document_type", default=False, action="store_true")
        parser.add_argument("-s", "--storage_path", default=False, action="store_true")
        parser.add_argument("-i", "--inbox-only", default=False, action="store_true")
        parser.add_argument(
            "--use-first",
            default=False,
            action="store_true",
            help=(
                "By default this command won't try to assign a correspondent "
                "if more than one matches the document.  Use this flag if "
                "you'd rather it just pick the first one it finds."
            ),
        )
        parser.add_argument(
            "-f",
            "--overwrite",
            default=False,
            action="store_true",
            help=(
                "If set, the document retagger will overwrite any previously "
                "set correspondent, document and remove correspondents, types "
                "and tags that do not match anymore due to changed rules."
            ),
        )
        self.add_argument_progress_bar_mixin(parser)
        parser.add_argument(
            "--suggest",
            default=False,
            action="store_true",
            help="Return the suggestion, don't change anything.",
        )
        parser.add_argument(
            "--base-url",
            help="The base URL to use to build the link to the documents.",
        )
        parser.add_argument(
            "--id-range",
            help="A range of document ids on which the retagging should be applied.",
            nargs=2,
            type=int,
        )

    def handle(self, *args, **options):
        self.handle_progress_bar_mixin(**options)

        if options["inbox_only"]:
            queryset = Document.objects.filter(tags__is_inbox_tag=True)
        else:
            queryset = Document.objects.all()

        if options["id_range"]:
            queryset = queryset.filter(
                id__range=(options["id_range"][0], options["id_range"][1]),
            )

        documents = queryset.distinct()

        classifier = load_classifier()

        for document in track(
            documents,
            total=documents.count(),
            disable=self.no_progress_bar,
        ):
            if options["correspondent"]:
                set_correspondent(
                    sender=None,
                    document=document,
                    classifier=classifier,
                    replace=options["overwrite"],
                    use_first=options["use_first"],
                    suggest=options["suggest"],
                    base_url=options["base_url"],
                    stdout=self.stdout,
                    style_func=self.style,
                )

            if options["document_type"]:
                set_document_type(
                    sender=None,
                    document=document,
                    classifier=classifier,
                    replace=options["overwrite"],
                    use_first=options["use_first"],
                    suggest=options["suggest"],
                    base_url=options["base_url"],
                    stdout=self.stdout,
                    style_func=self.style,
                )

            if options["tags"]:
                set_tags(
                    sender=None,
                    document=document,
                    classifier=classifier,
                    replace=options["overwrite"],
                    suggest=options["suggest"],
                    base_url=options["base_url"],
                    stdout=self.stdout,
                    style_func=self.style,
                )
            if options["storage_path"]:
                set_storage_path(
                    sender=None,
                    document=document,
                    classifier=classifier,
                    replace=options["overwrite"],
                    use_first=options["use_first"],
                    suggest=options["suggest"],
                    base_url=options["base_url"],
                    stdout=self.stdout,
                    style_func=self.style,
                )
