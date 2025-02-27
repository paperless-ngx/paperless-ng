import os
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.test import override_settings

from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import FileSystemAssertsMixin
from paperless.checks import audit_log_check
from paperless.checks import binaries_check
from paperless.checks import debug_mode_check
from paperless.checks import paths_check
from paperless.checks import settings_values_check


class TestChecks(DirectoriesMixin, TestCase):
    def test_binaries(self):
        self.assertEqual(binaries_check(None), [])

    @override_settings(CONVERT_BINARY="uuuhh")
    def test_binaries_fail(self):
        self.assertEqual(len(binaries_check(None)), 1)

    def test_paths_check(self):
        self.assertEqual(paths_check(None), [])

    @override_settings(
        MEDIA_ROOT="uuh",
        DATA_DIR="whatever",
        CONSUMPTION_DIR="idontcare",
    )
    def test_paths_check_dont_exist(self):
        msgs = paths_check(None)
        self.assertEqual(len(msgs), 3, str(msgs))

        for msg in msgs:
            self.assertTrue(msg.msg.endswith("is set but doesn't exist."))

    def test_paths_check_no_access(self):
        Path(self.dirs.data_dir).chmod(0o000)
        Path(self.dirs.media_dir).chmod(0o000)
        Path(self.dirs.consumption_dir).chmod(0o000)

        self.addCleanup(os.chmod, self.dirs.data_dir, 0o777)
        self.addCleanup(os.chmod, self.dirs.media_dir, 0o777)
        self.addCleanup(os.chmod, self.dirs.consumption_dir, 0o777)

        msgs = paths_check(None)
        self.assertEqual(len(msgs), 3)

        for msg in msgs:
            self.assertTrue(msg.msg.endswith("is not writeable"))

    @override_settings(DEBUG=False)
    def test_debug_disabled(self):
        self.assertEqual(debug_mode_check(None), [])

    @override_settings(DEBUG=True)
    def test_debug_enabled(self):
        self.assertEqual(len(debug_mode_check(None)), 1)


class TestSettingsChecksAgainstDefaults(DirectoriesMixin, TestCase):
    def test_all_valid(self):
        """
        GIVEN:
            - Default settings
        WHEN:
            - Settings are validated
        THEN:
            - No system check errors reported
        """
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 0)


class TestOcrSettingsChecks(DirectoriesMixin, TestCase):
    @override_settings(OCR_OUTPUT_TYPE="notapdf")
    def test_invalid_output_type(self):
        """
        GIVEN:
            - Default settings
            - OCR output type is invalid
        WHEN:
            - Settings are validated
        THEN:
            - system check error reported for OCR output type
        """
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 1)

        msg = msgs[0]

        self.assertIn('OCR output type "notapdf"', msg.msg)

    @override_settings(OCR_MODE="makeitso")
    def test_invalid_ocr_type(self):
        """
        GIVEN:
            - Default settings
            - OCR type is invalid
        WHEN:
            - Settings are validated
        THEN:
            - system check error reported for OCR type
        """
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 1)

        msg = msgs[0]

        self.assertIn('OCR output mode "makeitso"', msg.msg)

    @override_settings(OCR_MODE="skip_noarchive")
    def test_deprecated_ocr_type(self):
        """
        GIVEN:
            - Default settings
            - OCR type is deprecated
        WHEN:
            - Settings are validated
        THEN:
            - deprecation warning reported for OCR type
        """
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 1)

        msg = msgs[0]

        self.assertIn("deprecated", msg.msg)

    @override_settings(OCR_SKIP_ARCHIVE_FILE="invalid")
    def test_invalid_ocr_skip_archive_file(self):
        """
        GIVEN:
            - Default settings
            - OCR_SKIP_ARCHIVE_FILE is invalid
        WHEN:
            - Settings are validated
        THEN:
            - system check error reported for OCR_SKIP_ARCHIVE_FILE
        """
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 1)

        msg = msgs[0]

        self.assertIn('OCR_SKIP_ARCHIVE_FILE setting "invalid"', msg.msg)

    @override_settings(OCR_CLEAN="cleanme")
    def test_invalid_ocr_clean(self):
        """
        GIVEN:
            - Default settings
            - OCR cleaning type is invalid
        WHEN:
            - Settings are validated
        THEN:
            - system check error reported for OCR cleaning type
        """
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 1)

        msg = msgs[0]

        self.assertIn('OCR clean mode "cleanme"', msg.msg)


class TestTimezoneSettingsChecks(DirectoriesMixin, TestCase):
    @override_settings(TIME_ZONE="TheMoon\\MyCrater")
    def test_invalid_timezone(self):
        """
        GIVEN:
            - Default settings
            - Timezone is invalid
        WHEN:
            - Settings are validated
        THEN:
            - system check error reported for timezone
        """
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 1)

        msg = msgs[0]

        self.assertIn('Timezone "TheMoon\\MyCrater"', msg.msg)


class TestBarcodeSettingsChecks(DirectoriesMixin, TestCase):
    @override_settings(CONSUMER_BARCODE_SCANNER="Invalid")
    def test_barcode_scanner_invalid(self):
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 1)

        msg = msgs[0]

        self.assertIn('Invalid Barcode Scanner "Invalid"', msg.msg)

    @override_settings(CONSUMER_BARCODE_SCANNER="")
    def test_barcode_scanner_empty(self):
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 1)

        msg = msgs[0]

        self.assertIn('Invalid Barcode Scanner ""', msg.msg)

    @override_settings(CONSUMER_BARCODE_SCANNER="PYZBAR")
    def test_barcode_scanner_valid(self):
        msgs = settings_values_check(None)
        self.assertEqual(len(msgs), 0)


class TestEmailCertSettingsChecks(DirectoriesMixin, FileSystemAssertsMixin, TestCase):
    @override_settings(EMAIL_CERTIFICATE_FILE=Path("/tmp/not_actually_here.pem"))
    def test_not_valid_file(self):
        """
        GIVEN:
            - Default settings
            - Email certificate is set
        WHEN:
            - Email certificate file doesn't exist
        THEN:
            - system check error reported for email certificate
        """
        self.assertIsNotFile("/tmp/not_actually_here.pem")

        msgs = settings_values_check(None)

        self.assertEqual(len(msgs), 1)

        msg = msgs[0]

        self.assertIn("Email cert /tmp/not_actually_here.pem is not a file", msg.msg)


class TestAuditLogChecks(TestCase):
    def test_was_enabled_once(self):
        """
        GIVEN:
            - Audit log is not enabled
        WHEN:
            - Database tables contain audit log entry
        THEN:
            - system check error reported for disabling audit log
        """
        introspect_mock = mock.MagicMock()
        introspect_mock.introspection.table_names.return_value = ["auditlog_logentry"]
        with override_settings(AUDIT_LOG_ENABLED=False):
            with mock.patch.dict(
                "paperless.checks.connections",
                {"default": introspect_mock},
            ):
                msgs = audit_log_check(None)

                self.assertEqual(len(msgs), 1)

                msg = msgs[0]

                self.assertIn(
                    ("auditlog table was found but audit log is disabled."),
                    msg.msg,
                )
