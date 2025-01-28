import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from PIL import Image

from documents.parsers import DocumentParser
from documents.parsers import ParseError
from documents.parsers import make_thumbnail_from_pdf
from documents.utils import maybe_override_pixel_limit
from documents.utils import run_subprocess
from paperless.config import OcrConfig
from paperless.models import ArchiveFileChoices
from paperless.models import CleanChoices
from paperless.models import ModeChoices


class NoTextFoundException(Exception):
    pass


class RtlLanguageException(Exception):
    pass


class RasterisedDocumentParser(DocumentParser):
    """
    This parser uses Tesseract to try and get some text out of a rasterised
    image, whether it's a PDF, or other graphical format (JPEG, TIFF, etc.)
    """

    logging_name = "paperless.parsing.tesseract"

    def get_settings(self) -> OcrConfig:
        """
        This parser uses the OCR configuration settings to parse documents
        """
        return OcrConfig()

    def get_page_count(self, document_path, mime_type):
        page_count = None
        if mime_type == "application/pdf":
            try:
                import pikepdf

                with pikepdf.Pdf.open(document_path) as pdf:
                    page_count = len(pdf.pages)
            except Exception as e:
                self.log.warning(
                    f"Unable to determine PDF page count {document_path}: {e}",
                )
        return page_count

    def extract_metadata(self, document_path, mime_type):
        result = []
        if mime_type == "application/pdf":
            import pikepdf

            namespace_pattern = re.compile(r"\{(.*)\}(.*)")

            pdf = pikepdf.open(document_path)
            meta = pdf.open_metadata()
            for key, value in meta.items():
                if isinstance(value, list):
                    value = " ".join([str(e) for e in value])
                value = str(value)
                try:
                    m = namespace_pattern.match(key)
                    if m is None:  # pragma: no cover
                        continue
                    namespace = m.group(1)
                    key_value = m.group(2)
                    try:
                        namespace.encode("utf-8")
                        key_value.encode("utf-8")
                    except UnicodeEncodeError as e:  # pragma: no cover
                        self.log.debug(f"Skipping metadata key {key}: {e}")
                        continue
                    result.append(
                        {
                            "namespace": namespace,
                            "prefix": meta.REVERSE_NS[namespace],
                            "key": key_value,
                            "value": value,
                        },
                    )
                except Exception as e:
                    self.log.warning(
                        f"Error while reading metadata {key}: {value}. Error: {e}",
                    )
        return result

    def get_thumbnail(self, document_path, mime_type, file_name=None):
        return make_thumbnail_from_pdf(
            self.archive_path or document_path,
            self.tempdir,
            self.logging_group,
        )

    def is_image(self, mime_type) -> bool:
        return mime_type in [
            "image/png",
            "image/jpeg",
            "image/tiff",
            "image/bmp",
            "image/gif",
            "image/webp",
        ]

    def has_alpha(self, image) -> bool:
        with Image.open(image) as im:
            return im.mode in ("RGBA", "LA")

    def remove_alpha(self, image_path: str) -> Path:
        no_alpha_image = Path(self.tempdir) / "image-no-alpha"
        run_subprocess(
            [
                settings.CONVERT_BINARY,
                "-alpha",
                "off",
                image_path,
                no_alpha_image,
            ],
            logger=self.log,
        )
        return no_alpha_image

    def get_dpi(self, image) -> int | None:
        try:
            with Image.open(image) as im:
                x, y = im.info["dpi"]
                return round(x)
        except Exception as e:
            self.log.warning(f"Error while getting DPI from image {image}: {e}")
            return None

    def calculate_a4_dpi(self, image) -> int | None:
        try:
            with Image.open(image) as im:
                width, height = im.size
                # divide image width by A4 width (210mm) in inches.
                dpi = int(width / (21 / 2.54))
                self.log.debug(f"Estimated DPI {dpi} based on image width {width}")
                return dpi

        except Exception as e:
            self.log.warning(f"Error while calculating DPI for image {image}: {e}")
            return None

    def extract_text(
        self,
        sidecar_file: Path | None,
        pdf_file: Path,
    ) -> str | None:
        # When re-doing OCR, the sidecar contains ONLY the new text, not
        # the whole text, so do not utilize it in that case
        if (
            sidecar_file is not None
            and os.path.isfile(sidecar_file)
            and self.settings.mode != "redo"
        ):
            text = self.read_file_handle_unicode_errors(sidecar_file)

            if "[OCR skipped on page" not in text:
                # This happens when there's already text in the input file.
                # The sidecar file will only contain text for OCR'ed pages.
                self.log.debug("Using text from sidecar file")
                return post_process_text(text)
            else:
                self.log.debug("Incomplete sidecar file: discarding.")

        # no success with the sidecar file, try PDF

        if not os.path.isfile(pdf_file):
            return None

        try:
            text = None
            with tempfile.NamedTemporaryFile(
                mode="w+",
                dir=self.tempdir,
            ) as tmp:
                run_subprocess(
                    [
                        "pdftotext",
                        "-q",
                        "-layout",
                        "-enc",
                        "UTF-8",
                        pdf_file,
                        tmp.name,
                    ],
                    logger=self.log,
                )
                text = self.read_file_handle_unicode_errors(Path(tmp.name))

            return post_process_text(text)

        except Exception:
            #  If pdftotext fails, fall back to OCR.
            self.log.warning(
                "Error while getting text from PDF document with pdftotext",
                exc_info=True,
            )
            # probably not a PDF file.
            return None

    def construct_ocrmypdf_parameters(
        self,
        input_file,
        mime_type,
        output_file,
        sidecar_file,
        safe_fallback=False,
    ):
        if TYPE_CHECKING:
            assert isinstance(self.settings, OcrConfig)
        ocrmypdf_args = {
            "input_file": input_file,
            "output_file": output_file,
            # need to use threads, since this will be run in daemonized
            # processes via the task library.
            "use_threads": True,
            "jobs": settings.THREADS_PER_WORKER,
            "language": self.settings.language,
            "output_type": self.settings.output_type,
            "progress_bar": False,
        }

        if "pdfa" in ocrmypdf_args["output_type"]:
            ocrmypdf_args["color_conversion_strategy"] = (
                self.settings.color_conversion_strategy
            )

        if self.settings.mode == ModeChoices.FORCE or safe_fallback:
            ocrmypdf_args["force_ocr"] = True
        elif self.settings.mode in {
            ModeChoices.SKIP,
            ModeChoices.SKIP_NO_ARCHIVE,
        }:
            ocrmypdf_args["skip_text"] = True
        elif self.settings.mode == ModeChoices.REDO:
            ocrmypdf_args["redo_ocr"] = True
        else:  # pragma: no cover
            raise ParseError(f"Invalid ocr mode: {self.settings.mode}")

        if self.settings.clean == CleanChoices.CLEAN:
            ocrmypdf_args["clean"] = True
        elif self.settings.clean == CleanChoices.FINAL:
            if self.settings.mode == ModeChoices.REDO:
                ocrmypdf_args["clean"] = True
            else:
                # --clean-final is not compatible with --redo-ocr
                ocrmypdf_args["clean_final"] = True

        if self.settings.deskew and self.settings.mode != ModeChoices.REDO:
            # --deskew is not compatible with --redo-ocr
            ocrmypdf_args["deskew"] = True

        if self.settings.rotate:
            ocrmypdf_args["rotate_pages"] = True
            ocrmypdf_args["rotate_pages_threshold"] = self.settings.rotate_threshold

        if self.settings.pages is not None and self.settings.pages > 0:
            ocrmypdf_args["pages"] = f"1-{self.settings.pages}"
        else:
            # sidecar is incompatible with pages
            ocrmypdf_args["sidecar"] = sidecar_file

        if self.is_image(mime_type):
            # This may be required, depending on the known information
            maybe_override_pixel_limit()

            dpi = self.get_dpi(input_file)
            a4_dpi = self.calculate_a4_dpi(input_file)

            if self.has_alpha(input_file):
                self.log.info(
                    f"Removing alpha layer from {input_file} "
                    "for compatibility with img2pdf",
                )
                # Replace the input file with the non-alpha
                ocrmypdf_args["input_file"] = self.remove_alpha(input_file)

            if dpi:
                self.log.debug(f"Detected DPI for image {input_file}: {dpi}")
                ocrmypdf_args["image_dpi"] = dpi
            elif self.settings.image_dpi is not None:
                ocrmypdf_args["image_dpi"] = self.settings.image_dpi
            elif a4_dpi:
                ocrmypdf_args["image_dpi"] = a4_dpi
            else:
                raise ParseError(
                    f"Cannot produce archive PDF for image {input_file}, "
                    f"no DPI information is present in this image and "
                    f"OCR_IMAGE_DPI is not set.",
                )
            if ocrmypdf_args["image_dpi"] < 70:  # pragma: no cover
                self.log.warning(
                    f"Image DPI of {ocrmypdf_args['image_dpi']} is low, OCR may fail",
                )

        if self.settings.user_args is not None:
            try:
                ocrmypdf_args = {**ocrmypdf_args, **self.settings.user_args}
            except Exception as e:
                self.log.warning(
                    f"There is an issue with PAPERLESS_OCR_USER_ARGS, so "
                    f"they will not be used. Error: {e}",
                )

        if (
            self.settings.max_image_pixel is not None
            and self.settings.max_image_pixel >= 0
        ):
            # Convert pixels to mega-pixels and provide to ocrmypdf
            max_pixels_mpixels = self.settings.max_image_pixel / 1_000_000.0
            msg = (
                "OCR pixel limit is disabled!"
                if max_pixels_mpixels == 0
                else f"Calculated {max_pixels_mpixels} megapixels for OCR"
            )
            self.log.debug(msg)
            ocrmypdf_args["max_image_mpixels"] = max_pixels_mpixels

        return ocrmypdf_args

    def parse(self, document_path: Path, mime_type, file_name=None):
        # This forces tesseract to use one core per page.
        os.environ["OMP_THREAD_LIMIT"] = "1"
        VALID_TEXT_LENGTH = 50

        if mime_type == "application/pdf":
            text_original = self.extract_text(None, document_path)
            original_has_text = (
                text_original is not None and len(text_original) > VALID_TEXT_LENGTH
            )
        else:
            text_original = None
            original_has_text = False

        # If the original has text, and the user doesn't want an archive,
        # we're done here
        skip_archive_for_text = (
            self.settings.mode == ModeChoices.SKIP_NO_ARCHIVE
            or self.settings.skip_archive_file
            in {
                ArchiveFileChoices.WITH_TEXT,
                ArchiveFileChoices.ALWAYS,
            }
        )
        if skip_archive_for_text and original_has_text:
            self.log.debug("Document has text, skipping OCRmyPDF entirely.")
            self.text = text_original
            return

        # Either no text was in the original or there should be an archive
        # file created, so OCR the file and create an archive with any
        # text located via OCR

        import ocrmypdf
        from ocrmypdf import EncryptedPdfError
        from ocrmypdf import InputFileError
        from ocrmypdf import SubprocessOutputError
        from ocrmypdf.exceptions import DigitalSignatureError

        archive_path = Path(os.path.join(self.tempdir, "archive.pdf"))
        sidecar_file = Path(os.path.join(self.tempdir, "sidecar.txt"))

        args = self.construct_ocrmypdf_parameters(
            document_path,
            mime_type,
            archive_path,
            sidecar_file,
        )

        def safe_fallback_ocr():
            archive_path_fallback = Path(
                os.path.join(self.tempdir, "archive-fallback.pdf"),
            )
            sidecar_file_fallback = Path(
                os.path.join(self.tempdir, "sidecar-fallback.txt"),
            )

            # Attempt to run OCR with safe settings.

            args = self.construct_ocrmypdf_parameters(
                document_path,
                mime_type,
                archive_path_fallback,
                sidecar_file_fallback,
                safe_fallback=True,
            )

            try:
                self.log.debug(f"Fallback: Calling OCRmyPDF with args: {args}")
                ocrmypdf.ocr(**args)

                # Don't return the archived file here, since this file
                # is bigger and blurry due to --force-ocr.

                self.text = self.extract_text(
                    sidecar_file_fallback,
                    archive_path_fallback,
                )

            except Exception as e:
                # If this fails, we have a serious issue at hand.
                raise ParseError(f"{e.__class__.__name__}: {e!s}") from e

        try:
            self.log.debug(f"Calling OCRmyPDF with args: {args}")
            ocrmypdf.ocr(**args)

            if self.settings.skip_archive_file != ArchiveFileChoices.ALWAYS:
                self.archive_path = archive_path

            self.text = self.extract_text(sidecar_file, archive_path)

            if not self.text:
                raise NoTextFoundException("No text was found in the original document")
        except (DigitalSignatureError, EncryptedPdfError):
            self.log.warning(
                "This file is encrypted and/or signed, OCR is impossible. Using "
                "any text present in the original file.",
            )
            if original_has_text:
                self.text = text_original
        except SubprocessOutputError as e:
            if "Ghostscript rasterizing failed" in str(e):
                safe_fallback_ocr()
            else:
                if "Ghostscript PDF/A rendering" in str(e):
                    self.log.warning(
                        "Ghostscript PDF/A rendering failed, consider setting "
                        "PAPERLESS_OCR_USER_ARGS: '{\"continue_on_soft_render_error\": true}'",
                    )

                raise ParseError(
                    f"SubprocessOutputError: {e!s}. See logs for more information.",
                ) from e
        except (NoTextFoundException, InputFileError) as e:
            self.log.warning(
                f"Encountered an error while running OCR: {e!s}. "
                f"Attempting force OCR to get the text.",
            )

            safe_fallback_ocr()

        except Exception as e:
            # Anything else is probably serious.
            raise ParseError(f"{e.__class__.__name__}: {e!s}") from e

        # As a last resort, if we still don't have any text for any reason,
        # try to extract the text from the original document.
        if not self.text:
            if original_has_text:
                self.text = text_original
            else:
                self.log.warning(
                    f"No text was found in {document_path}, the content will be empty.",
                )
                self.text = ""


def post_process_text(text):
    if not text:
        return None

    collapsed_spaces = re.sub(r"([^\S\r\n]+)", " ", text)
    no_leading_whitespace = re.sub(r"([\n\r]+)([^\S\n\r]+)", "\\1", collapsed_spaces)
    no_trailing_whitespace = re.sub(r"([^\S\n\r]+)$", "", no_leading_whitespace)

    # TODO: this needs a rework
    # replace \0 prevents issues with saving to postgres.
    # text may contain \0 when this character is present in PDF files.
    return no_trailing_whitespace.strip().replace("\0", " ")
