from django.apps import AppConfig
from django.conf import settings

from paperless_xml.signals import xml_consumer_declaration


class PaperlessXMLConfig(AppConfig):
    name = "paperless_xml"

    def ready(self):
        from documents.signals import document_consumer_declaration

        if settings.RECHNUNGLESS_ENABLED:
            document_consumer_declaration.connect(xml_consumer_declaration)

        AppConfig.ready(self)
