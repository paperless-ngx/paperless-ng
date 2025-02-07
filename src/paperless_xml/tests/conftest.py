from collections.abc import Generator
from pathlib import Path

import pytest

from paperless_text.parsers import TextDocumentParser


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    return (Path(__file__).parent / Path("samples")).resolve()


@pytest.fixture()
def text_parser() -> Generator[TextDocumentParser, None, None]:
    try:
        parser = TextDocumentParser(logging_group=None)
        yield parser
    finally:
        parser.cleanup()


@pytest.fixture(scope="session")
def sample_txt_file(sample_dir: Path) -> Path:
    return sample_dir / "test.txt"


@pytest.fixture(scope="session")
def malformed_txt_file(sample_dir: Path) -> Path:
    return sample_dir / "decode_error.txt"
