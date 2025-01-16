import base64
import json
from datetime import datetime
from pathlib import Path

import httpx
from django.conf import settings
from django.utils.timezone import is_naive
from django.utils.timezone import make_aware

from documents.parsers import ParseError
from documents.parsers import make_thumbnail_from_pdf
from paperless_text.parsers import TextDocumentParser


class XMLDocumentParser(TextDocumentParser):
    """
    This parser parses a xml document (.xml)
    """

    logging_name = "paperless.parsing.xml"

    is_invoice = False

    def get_thumbnail(self, document_path: Path, mime_type, file_name=None) -> Path:
        if self.is_invoice:
            return make_thumbnail_from_pdf(
                self.archive_path,
                self.tempdir,
                self.logging_group,
            )
        else:
            return super().get_thumbnail(document_path, mime_type, file_name)

    def parse(self, document_path, mime_type, file_name=None):
        super().parse(document_path, mime_type, file_name)
        self.is_invoice = False

        header = {"Content-Type": "application/xml"}
        url = settings.RECHNUNGLESS_ENDPOINT
        httpResponse = httpx.post(
            url + "/convert",
            headers=header,
            data=self.text,
            timeout=60.0,
        )
        if httpResponse.status_code == httpx.codes.INTERNAL_SERVER_ERROR:
            raise ParseError("Server Error: " + str(httpResponse.content))
        if httpResponse.status_code not in (
            httpx.codes.OK,
            httpx.codes.UNPROCESSABLE_ENTITY,
        ):
            raise ParseError(
                "Unknown Error: HTTP"
                + str(httpResponse.status_code)
                + " "
                + str(httpResponse.content),
            )
        response = json.loads(httpResponse.content)

        if response["result"] == "failed":
            message = "Conversion failed: \n"
            for msg in response["messages"]:
                message += msg
            self.log.info(f"Invalid schema: {message}")
            self.is_invoice = False
            return
        if httpResponse.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            message = "The XML file is not valid:"
            for msg in response["messages"]:
                message += "\n" + msg
            self.log.info(f"Invalid schema: {message}")
            self.is_invoice = False
            return

        if response["result"] == "invalid":
            contStr = str(httpResponse.content)
            self.log.warning(f"The file received is technically invalid: {contStr}")

        self.archive_path = Path(self.tempdir, "invoice.pdf")
        self.is_invoice = True

        with self.archive_path.open("wb") as archiveFile:
            archiveFile.write(base64.b64decode(response["archive_pdf"]))

        if "issue_date" in response:
            self.date = datetime.strptime(response["issue_date"], "%Y%m%d")
            if is_naive(self.date):
                self.date = make_aware(self.date)
