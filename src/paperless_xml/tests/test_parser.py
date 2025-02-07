from pathlib import Path

from paperless_text.parsers import TextDocumentParser


class TestTextParser:
    def test_thumbnail(self, text_parser: TextDocumentParser, sample_txt_file: Path):
        # just make sure that it does not crash
        f = text_parser.get_thumbnail(sample_txt_file, "text/plain")
        assert f.exists()
        assert f.is_file()

    def test_parse(self, text_parser: TextDocumentParser, sample_txt_file: Path):
        text_parser.parse(sample_txt_file, "text/plain")

        assert text_parser.get_text() == "This is a test file.\n"
        assert text_parser.get_archive_path() is None

    def test_parse_invalid_bytes(
        self,
        text_parser: TextDocumentParser,
        malformed_txt_file: Path,
    ):
        """
        GIVEN:
            - Text file which contains invalid UTF bytes
        WHEN:
            - The file is parsed
        THEN:
            - Parsing continues
            - Invalid bytes are removed
        """

        text_parser.parse(malformed_txt_file, "text/plain")

        assert text_parser.get_text() == "Pantothens�ure\n"
        assert text_parser.get_archive_path() is None
