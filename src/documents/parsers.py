import datetime
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from re import Match

from django.conf import settings
from django.utils import timezone

from documents.loggers import LoggingMixin
from documents.signals import document_consumer_declaration
from documents.utils import copy_file_with_basic_stats
from documents.utils import run_subprocess

# This regular expression will try to find dates in the document at
# hand and will match the following formats:
# - XX.YY.ZZZZ with XX + YY being 1 or 2 and ZZZZ being 2 or 4 digits
# - XX/YY/ZZZZ with XX + YY being 1 or 2 and ZZZZ being 2 or 4 digits
# - XX-YY-ZZZZ with XX + YY being 1 or 2 and ZZZZ being 2 or 4 digits
# - ZZZZ.XX.YY with XX + YY being 1 or 2 and ZZZZ being 2 or 4 digits
# - ZZZZ/XX/YY with XX + YY being 1 or 2 and ZZZZ being 2 or 4 digits
# - ZZZZ-XX-YY with XX + YY being 1 or 2 and ZZZZ being 2 or 4 digits
# - XX. MONTH ZZZZ with XX being 1 or 2 and ZZZZ being 2 or 4 digits
# - MONTH ZZZZ, with ZZZZ being 4 digits
# - MONTH XX, ZZZZ with XX being 1 or 2 and ZZZZ being 4 digits
# - XX MON ZZZZ with XX being 1 or 2 and ZZZZ being 4 digits. MONTH is 3 letters
# - XXPP MONTH ZZZZ with XX being 1 or 2 and PP being 2 letters and ZZZZ being 4 digits

# TODO: isn't there a date parsing library for this?

DATE_REGEX = re.compile(
    r"(\b|(?!=([_-])))(\d{1,2})[\.\/-](\d{1,2})[\.\/-](\d{4}|\d{2})(\b|(?=([_-])))|"
    r"(\b|(?!=([_-])))(\d{4}|\d{2})[\.\/-](\d{1,2})[\.\/-](\d{1,2})(\b|(?=([_-])))|"
    r"(\b|(?!=([_-])))(\d{1,2}[\. ]+[a-zéûäëčžúřěáíóńźçŞğü]{3,9} \d{4}|[a-zéûäëčžúřěáíóńźçŞğü]{3,9} \d{1,2}, \d{4})(\b|(?=([_-])))|"
    r"(\b|(?!=([_-])))([^\W\d_]{3,9} \d{1,2}, (\d{4}))(\b|(?=([_-])))|"
    r"(\b|(?!=([_-])))([^\W\d_]{3,9} \d{4})(\b|(?=([_-])))|"
    r"(\b|(?!=([_-])))(\d{1,2}[^ ]{2}[\. ]+[^ ]{3,9}[ \.\/-]\d{4})(\b|(?=([_-])))|"
    r"(\b|(?!=([_-])))(\b\d{1,2}[ \.\/-][a-zéûäëčžúřěáíóńźçŞğü]{3}[ \.\/-]\d{4})(\b|(?=([_-])))",
    re.IGNORECASE,
)


logger = logging.getLogger("paperless.parsing")


@lru_cache(maxsize=8)
def is_mime_type_supported(mime_type: str) -> bool:
    """
    Returns True if the mime type is supported, False otherwise
    """
    return get_parser_class_for_mime_type(mime_type) is not None


@lru_cache(maxsize=8)
def get_default_file_extension(mime_type: str) -> str:
    """
    Returns the default file extension for a mimetype, or
    an empty string if it could not be determined
    """
    for response in document_consumer_declaration.send(None):
        parser_declaration = response[1]
        supported_mime_types = parser_declaration["mime_types"]

        if mime_type in supported_mime_types:
            return supported_mime_types[mime_type]

    ext = mimetypes.guess_extension(mime_type)
    if ext:
        return ext
    else:
        return ""


@lru_cache(maxsize=8)
def is_file_ext_supported(ext: str) -> bool:
    """
    Returns True if the file extension is supported, False otherwise
    TODO: Investigate why this really exists, why not use mimetype
    """
    if ext:
        return ext.lower() in get_supported_file_extensions()
    else:
        return False


def get_supported_file_extensions() -> set[str]:
    extensions = set()
    for response in document_consumer_declaration.send(None):
        parser_declaration = response[1]
        supported_mime_types = parser_declaration["mime_types"]

        for mime_type in supported_mime_types:
            extensions.update(mimetypes.guess_all_extensions(mime_type))
            # Python's stdlib might be behind, so also add what the parser
            # says is the default extension
            # This makes image/webp supported on Python < 3.11
            extensions.add(supported_mime_types[mime_type])

    return extensions


def get_parser_class_for_mime_type(mime_type: str) -> type["DocumentParser"] | None:
    """
    Returns the best parser (by weight) for the given mimetype or
    None if no parser exists
    """

    options = []

    for response in document_consumer_declaration.send(None):
        parser_declaration = response[1]
        supported_mime_types = parser_declaration["mime_types"]

        if mime_type in supported_mime_types:
            options.append(parser_declaration)

    if not options:
        return None

    best_parser = sorted(options, key=lambda _: _["weight"], reverse=True)[0]

    # Return the parser with the highest weight.
    return best_parser["parser"]


def run_convert(
    input_file,
    output_file,
    *,
    density=None,
    scale=None,
    alpha=None,
    strip=False,
    trim=False,
    type=None,
    depth=None,
    auto_orient=False,
    use_cropbox=False,
    extra=None,
    logging_group=None,
) -> None:
    environment = os.environ.copy()
    if settings.CONVERT_MEMORY_LIMIT:
        environment["MAGICK_MEMORY_LIMIT"] = settings.CONVERT_MEMORY_LIMIT
    if settings.CONVERT_TMPDIR:
        environment["MAGICK_TMPDIR"] = settings.CONVERT_TMPDIR

    args = [settings.CONVERT_BINARY]
    args += ["-density", str(density)] if density else []
    args += ["-scale", str(scale)] if scale else []
    args += ["-alpha", str(alpha)] if alpha else []
    args += ["-strip"] if strip else []
    args += ["-trim"] if trim else []
    args += ["-type", str(type)] if type else []
    args += ["-depth", str(depth)] if depth else []
    args += ["-auto-orient"] if auto_orient else []
    args += ["-define", "pdf:use-cropbox=true"] if use_cropbox else []
    args += [input_file, output_file]

    logger.debug("Execute: " + " ".join(args), extra={"group": logging_group})

    try:
        run_subprocess(args, environment, logger)
    except subprocess.CalledProcessError as e:
        raise ParseError(f"Convert failed at {args}") from e
    except Exception as e:  # pragma: no cover
        raise ParseError("Unknown error running convert") from e


def get_default_thumbnail() -> Path:
    """
    Returns the path to a generic thumbnail
    """
    return (Path(__file__).parent / "resources" / "document.webp").resolve()


def make_thumbnail_from_pdf_gs_fallback(in_path, temp_dir, logging_group=None) -> str:
    out_path = os.path.join(temp_dir, "convert_gs.webp")

    # if convert fails, fall back to extracting
    # the first PDF page as a PNG using Ghostscript
    logger.warning(
        "Thumbnail generation with ImageMagick failed, falling back "
        "to ghostscript. Check your /etc/ImageMagick-x/policy.xml!",
        extra={"group": logging_group},
    )
    # Ghostscript doesn't handle WebP outputs
    gs_out_path = os.path.join(temp_dir, "gs_out.png")
    cmd = [settings.GS_BINARY, "-q", "-sDEVICE=pngalpha", "-o", gs_out_path, in_path]

    try:
        try:
            run_subprocess(cmd, logger=logger)
        except subprocess.CalledProcessError as e:
            raise ParseError(f"Thumbnail (gs) failed at {cmd}") from e
        # then run convert on the output from gs to make WebP
        run_convert(
            density=300,
            scale="500x5000>",
            alpha="remove",
            strip=True,
            trim=False,
            auto_orient=True,
            input_file=gs_out_path,
            output_file=out_path,
            logging_group=logging_group,
        )

        return out_path

    except ParseError as e:
        logger.error(f"Unable to make thumbnail with Ghostscript: {e}")
        # The caller might expect a generated thumbnail that can be moved,
        # so we need to copy it before it gets moved.
        # https://github.com/paperless-ngx/paperless-ngx/issues/3631
        default_thumbnail_path = os.path.join(temp_dir, "document.webp")
        copy_file_with_basic_stats(get_default_thumbnail(), default_thumbnail_path)
        return default_thumbnail_path


def make_thumbnail_from_pdf(in_path, temp_dir, logging_group=None) -> Path:
    """
    The thumbnail of a PDF is just a 500px wide image of the first page.
    """
    out_path = temp_dir / "convert.webp"

    # Run convert to get a decent thumbnail
    try:
        run_convert(
            density=300,
            scale="500x5000>",
            alpha="remove",
            strip=True,
            trim=False,
            auto_orient=True,
            use_cropbox=True,
            input_file=f"{in_path}[0]",
            output_file=str(out_path),
            logging_group=logging_group,
        )
    except ParseError as e:
        logger.error(f"Unable to make thumbnail with convert: {e}")
        out_path = make_thumbnail_from_pdf_gs_fallback(in_path, temp_dir, logging_group)

    return out_path


def parse_date(filename, text) -> datetime.datetime | None:
    return next(parse_date_generator(filename, text), None)


def parse_date_generator(filename, text) -> Iterator[datetime.datetime]:
    """
    Returns the date of the document.
    """

    def __parser(ds: str, date_order: str) -> datetime.datetime:
        """
        Call dateparser.parse with a particular date ordering
        """
        import dateparser

        return dateparser.parse(
            ds,
            settings={
                "DATE_ORDER": date_order,
                "PREFER_DAY_OF_MONTH": "first",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": settings.TIME_ZONE,
            },
        )

    def __filter(date: datetime.datetime) -> datetime.datetime | None:
        if (
            date is not None
            and date.year > 1900
            and date <= timezone.now()
            and date.date() not in settings.IGNORE_DATES
        ):
            return date
        return None

    def __process_match(
        match: Match[str],
        date_order: str,
    ) -> datetime.datetime | None:
        date_string = match.group(0)

        try:
            date = __parser(date_string, date_order)
        except Exception:
            # Skip all matches that do not parse to a proper date
            date = None

        return __filter(date)

    def __process_content(content: str, date_order: str) -> Iterator[datetime.datetime]:
        for m in re.finditer(DATE_REGEX, content):
            date = __process_match(m, date_order)
            if date is not None:
                yield date

    # if filename date parsing is enabled, search there first:
    if settings.FILENAME_DATE_ORDER:
        yield from __process_content(filename, settings.FILENAME_DATE_ORDER)

    # Iterate through all regex matches in text and try to parse the date
    yield from __process_content(text, settings.DATE_ORDER)


class ParseError(Exception):
    pass


class DocumentParser(LoggingMixin):
    """
    Subclass this to make your own parser.  Have a look at
    `paperless_tesseract.parsers` for inspiration.
    """

    logging_name = "paperless.parsing"

    def __init__(self, logging_group, progress_callback=None):
        super().__init__()
        self.renew_logging_group()
        self.logging_group = logging_group
        self.settings = self.get_settings()
        settings.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        self.tempdir = Path(
            tempfile.mkdtemp(prefix="paperless-", dir=settings.SCRATCH_DIR),
        )

        self.archive_path = None
        self.text = None
        self.date: datetime.datetime | None = None
        self.progress_callback = progress_callback

    def progress(self, current_progress, max_progress):
        if self.progress_callback:
            self.progress_callback(current_progress, max_progress)

    def get_settings(self):  # pragma: no cover
        """
        A parser must implement this
        """
        raise NotImplementedError

    def read_file_handle_unicode_errors(self, filepath: Path) -> str:
        """
        Helper utility for reading from a file, and handling a problem with its
        unicode, falling back to ignoring the error to remove the invalid bytes
        """
        try:
            text = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            self.log.warning(f"Unicode error during text reading, continuing: {e}")
            text = filepath.read_bytes().decode("utf-8", errors="replace")
        return text

    def extract_metadata(self, document_path, mime_type):
        return []

    def get_page_count(self, document_path, mime_type):
        return None

    def parse(self, document_path, mime_type, file_name=None):
        raise NotImplementedError

    def get_archive_path(self):
        return self.archive_path

    def get_thumbnail(self, document_path, mime_type, file_name=None):
        """
        Returns the path to a file we can use as a thumbnail for this document.
        """
        raise NotImplementedError

    def get_text(self):
        return self.text

    def get_date(self) -> datetime.datetime | None:
        return self.date

    def cleanup(self):
        self.log.debug(f"Deleting directory {self.tempdir}")
        shutil.rmtree(self.tempdir)
