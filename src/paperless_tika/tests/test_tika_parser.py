import datetime
import zoneinfo
from http import HTTPStatus
from pathlib import Path

import pytest
from httpx import codes
from pytest_django.fixtures import SettingsWrapper
from pytest_httpx import HTTPXMock

from documents.parsers import ParseError
from paperless_tika.parsers import TikaDocumentParser


@pytest.mark.django_db()
class TestTikaParser:
    def test_parse(
        self,
        httpx_mock: HTTPXMock,
        settings: SettingsWrapper,
        tika_parser: TikaDocumentParser,
        sample_odt_file: Path,
    ):
        settings.TIME_ZONE = "America/Chicago"
        # Pretend parse response
        httpx_mock.add_response(
            json={
                "Content-Type": "application/vnd.oasis.opendocument.text",
                "X-TIKA:Parsed-By": [],
                "X-TIKA:content": "the content",
                "dcterms:created": "2020-11-21T00:00:00",
            },
        )
        # Pretend convert to PDF response
        httpx_mock.add_response(content=b"PDF document")

        tika_parser.parse(sample_odt_file, "application/vnd.oasis.opendocument.text")

        assert tika_parser.text == "the content"
        assert tika_parser.archive_path is not None
        with Path(tika_parser.archive_path).open("rb") as f:
            assert f.read() == b"PDF document"

        assert tika_parser.date == datetime.datetime(
            2020,
            11,
            21,
            tzinfo=zoneinfo.ZoneInfo("America/Chicago"),
        )

    def test_metadata(
        self,
        httpx_mock: HTTPXMock,
        tika_parser: TikaDocumentParser,
        sample_odt_file: Path,
    ):
        httpx_mock.add_response(
            json={
                "Content-Type": "application/vnd.oasis.opendocument.text",
                "X-TIKA:Parsed-By": [],
                "Some-key": "value",
                "dcterms:created": "2020-11-21T00:00:00",
            },
        )

        metadata = tika_parser.extract_metadata(
            sample_odt_file,
            "application/vnd.oasis.opendocument.text",
        )

        assert "dcterms:created" in [m["key"] for m in metadata]
        assert "Some-key" in [m["key"] for m in metadata]

    def test_convert_failure(
        self,
        httpx_mock: HTTPXMock,
        tika_parser: TikaDocumentParser,
        sample_odt_file: Path,
    ):
        """
        GIVEN:
            - Document needs to be converted to PDF
        WHEN:
            - Gotenberg server returns an error
        THEN:
            - Parse error is raised
        """
        # Pretend convert to PDF response
        httpx_mock.add_response(status_code=HTTPStatus.INTERNAL_SERVER_ERROR)

        with pytest.raises(ParseError):
            tika_parser.convert_to_pdf(sample_odt_file, None)

    @pytest.mark.parametrize(
        ("setting_value", "expected_form_value"),
        [
            ("pdfa", "PDF/A-2b"),
            ("pdfa-1", "PDF/A-2b"),
            ("pdfa-2", "PDF/A-2b"),
            ("pdfa-3", "PDF/A-3b"),
        ],
    )
    def test_request_pdf_a_format(
        self,
        setting_value: str,
        expected_form_value: str,
        httpx_mock: HTTPXMock,
        settings: SettingsWrapper,
        tika_parser: TikaDocumentParser,
        sample_odt_file: Path,
    ):
        """
        GIVEN:
            - Document needs to be converted to PDF
        WHEN:
            - Specific PDF/A format requested
        THEN:
            - Request to Gotenberg contains the expected PDF/A format string
        """
        settings.OCR_OUTPUT_TYPE = setting_value
        httpx_mock.add_response(
            status_code=codes.OK,
            content=b"PDF document",
            method="POST",
        )

        tika_parser.convert_to_pdf(sample_odt_file, None)

        request = httpx_mock.get_request()

        expected_field_name = "pdfa"

        content_type = request.headers["Content-Type"]
        assert "multipart/form-data" in content_type

        boundary = content_type.split("boundary=")[1]

        parts = request.content.split(f"--{boundary}".encode())

        form_field_found = any(
            f'name="{expected_field_name}"'.encode() in part
            and expected_form_value.encode() in part
            for part in parts
        )

        assert form_field_found

        httpx_mock.reset()
