import os
from pathlib import Path

import pytest

from documents.tests.utils import util_call_with_backoff
from paperless_tika.parsers import TikaDocumentParser


@pytest.mark.skipif(
    "PAPERLESS_CI_TEST" not in os.environ,
    reason="No Gotenberg/Tika servers to test with",
)
@pytest.mark.django_db()
class TestTikaParserAgainstServer:
    """
    This test case tests the Tika parsing against a live tika server,
    if the environment contains the correct value indicating such a server
    is available.
    """

    def test_basic_parse_odt(
        self,
        tika_parser: TikaDocumentParser,
        sample_odt_file: Path,
    ):
        """
        GIVEN:
            - An input ODT format document
        WHEN:
            - The document is parsed
        THEN:
            - Document content is correct
            - Document date is correct
        """
        util_call_with_backoff(
            tika_parser.parse,
            [sample_odt_file, "application/vnd.oasis.opendocument.text"],
        )

        assert (
            tika_parser.text
            == "This is an ODT test document, created September 14, 2022"
        )
        assert tika_parser.archive_path is not None
        assert b"PDF-" in tika_parser.archive_path.read_bytes()[:10]

        # TODO: Unsure what can set the Creation-Date field in a document, enable when possible
        # self.assertEqual(tika_parser.date, datetime.datetime(2022, 9, 14))

    def test_basic_parse_docx(
        self,
        tika_parser: TikaDocumentParser,
        sample_docx_file: Path,
    ):
        """
        GIVEN:
            - An input DOCX format document
        WHEN:
            - The document is parsed
        THEN:
            - Document content is correct
            - Document date is correct
        """
        util_call_with_backoff(
            tika_parser.parse,
            [
                sample_docx_file,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ],
        )

        assert (
            tika_parser.text
            == "This is an DOCX test document, also made September 14, 2022"
        )
        assert tika_parser.archive_path is not None
        with Path(tika_parser.archive_path).open("rb") as f:
            assert b"PDF-" in f.read()[:10]

        # self.assertEqual(tika_parser.date, datetime.datetime(2022, 9, 14))

    def test_basic_parse_doc(
        self,
        tika_parser: TikaDocumentParser,
        sample_doc_file: Path,
    ):
        """
        GIVEN:
            - An input DOC format document
        WHEN:
            - The document is parsed
        THEN:
            - Document content is correct
            - Document date is correct
        """
        util_call_with_backoff(
            tika_parser.parse,
            [sample_doc_file, "application/msword"],
        )

        assert (
            "This is a test document, saved in the older .doc format"
            in tika_parser.text
        )
        assert tika_parser.archive_path is not None
        with Path(tika_parser.archive_path).open("rb") as f:
            assert b"PDF-" in f.read()[:10]

    def test_tika_fails_multi_part(
        self,
        tika_parser: TikaDocumentParser,
        sample_broken_odt: Path,
    ):
        """
        GIVEN:
            - An input ODT format document
            - The document is known to crash Tika when uploaded via multi-part form data
        WHEN:
            - The document is parsed
        THEN:
            - Document content is correct
            - Document date is correct
        See also:
            - https://issues.apache.org/jira/browse/TIKA-4110
        """
        util_call_with_backoff(
            tika_parser.parse,
            [sample_broken_odt, "application/vnd.oasis.opendocument.text"],
        )

        assert tika_parser.archive_path is not None
        with Path(tika_parser.archive_path).open("rb") as f:
            assert b"PDF-" in f.read()[:10]
