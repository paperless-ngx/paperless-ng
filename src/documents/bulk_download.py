from pathlib import Path
from typing import TYPE_CHECKING
from typing import NoReturn
from zipfile import ZipFile

from documents.models import Document

if TYPE_CHECKING:
    from collections.abc import Callable


class BulkArchiveStrategy:
    def __init__(self, zipf: ZipFile, *, follow_formatting: bool = False) -> None:
        self.zipf: ZipFile = zipf
        if follow_formatting:
            self.make_unique_filename: Callable[..., Path | str] = (
                self._formatted_filepath
            )
        else:
            self.make_unique_filename = self._filename_only

    def _filename_only(
        self,
        doc: Document,
        *,
        archive: bool = False,
        folder: str = "",
    ) -> str:
        """
        Constructs a unique name for the given document to be used inside the
        zip file.

        The filename might not be unique enough, so a counter is appended if needed
        """
        counter = 0
        while True:
            filename: str = folder + doc.get_public_filename(
                archive=archive,
                counter=counter,
            )
            if filename in self.zipf.namelist():
                counter += 1
            else:
                return filename

    def _formatted_filepath(
        self,
        doc: Document,
        *,
        archive: bool = False,
        folder: str = "",
    ) -> Path:
        """
        Constructs a full file path for the given document to be used inside
        the zipfile.

        The path is already unique, as handled when a document is consumed or updated
        """
        if archive and doc.has_archive_version:
            if TYPE_CHECKING:
                assert doc.archive_filename is not None
            in_archive_path: Path = Path(folder) / doc.archive_filename
        else:
            if TYPE_CHECKING:
                assert doc.filename is not None
            in_archive_path = Path(folder) / doc.filename

        return in_archive_path

    def add_document(self, doc: Document) -> NoReturn:
        raise NotImplementedError  # pragma: no cover


class OriginalsOnlyStrategy(BulkArchiveStrategy):
    def add_document(self, doc: Document) -> None:
        self.zipf.write(doc.source_path, self.make_unique_filename(doc))


class ArchiveOnlyStrategy(BulkArchiveStrategy):
    def add_document(self, doc: Document) -> None:
        if doc.has_archive_version:
            if TYPE_CHECKING:
                assert doc.archive_path is not None
            self.zipf.write(
                doc.archive_path,
                self.make_unique_filename(doc, archive=True),
            )
        else:
            self.zipf.write(doc.source_path, self.make_unique_filename(doc))


class OriginalAndArchiveStrategy(BulkArchiveStrategy):
    def add_document(self, doc: Document) -> None:
        if doc.has_archive_version:
            if TYPE_CHECKING:
                assert doc.archive_path is not None
            self.zipf.write(
                doc.archive_path,
                self.make_unique_filename(doc, archive=True, folder="archive/"),
            )

        self.zipf.write(
            doc.source_path,
            self.make_unique_filename(doc, folder="originals/"),
        )
