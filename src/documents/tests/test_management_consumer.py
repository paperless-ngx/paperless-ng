import filecmp
import os
import shutil
from pathlib import Path
from threading import Thread
from time import sleep
from unittest import mock

from django.conf import settings
from django.core.management import CommandError
from django.core.management import call_command
from django.test import TransactionTestCase
from django.test import override_settings

from documents.consumer import ConsumerError
from documents.data_models import ConsumableDocument
from documents.management.commands import document_consumer
from documents.models import Tag
from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import DocumentConsumeDelayMixin


class ConsumerThread(Thread):
    def __init__(self):
        super().__init__()
        self.cmd = document_consumer.Command()
        self.cmd.stop_flag.clear()

    def run(self) -> None:
        self.cmd.handle(directory=settings.CONSUMPTION_DIR, oneshot=False, testing=True)

    def stop(self):
        # Consumer checks this every second.
        self.cmd.stop_flag.set()


def chunked(size, source):
    for i in range(0, len(source), size):
        yield source[i : i + size]


class ConsumerThreadMixin(DocumentConsumeDelayMixin):
    """
    Provides a thread which runs the consumer management command at setUp
    and stops it at tearDown
    """

    sample_file: Path = (
        Path(__file__).parent / Path("samples") / Path("simple.pdf")
    ).resolve()

    def setUp(self) -> None:
        super().setUp()
        self.t = None

    def t_start(self):
        self.t = ConsumerThread()
        self.t.start()
        # give the consumer some time to do initial work
        sleep(1)

    def tearDown(self) -> None:
        if self.t:
            # set the stop flag
            self.t.stop()
            # wait for the consumer to exit.
            self.t.join()
            self.t = None

        super().tearDown()

    def wait_for_task_mock_call(self, expected_call_count=1):
        n = 0
        while n < 50:
            if self.consume_file_mock.call_count >= expected_call_count:
                # give task_mock some time to finish and raise errors
                sleep(1)
                return
            n += 1
            sleep(0.1)

    # A bogus async_task that will simply check the file for
    # completeness and raise an exception otherwise.
    def bogus_task(
        self,
        input_doc: ConsumableDocument,
        overrides=None,
    ):
        eq = filecmp.cmp(input_doc.original_file, self.sample_file, shallow=False)
        if not eq:
            print("Consumed an INVALID file.")  # noqa: T201
            raise ConsumerError("Incomplete File READ FAILED")
        else:
            print("Consumed a perfectly valid file.")  # noqa: T201

    def slow_write_file(self, target, *, incomplete=False):
        with open(self.sample_file, "rb") as f:
            pdf_bytes = f.read()

        if incomplete:
            pdf_bytes = pdf_bytes[: len(pdf_bytes) - 100]

        with open(target, "wb") as f:
            # this will take 2 seconds, since the file is about 20k.
            print("Start writing file.")  # noqa: T201
            for b in chunked(1000, pdf_bytes):
                f.write(b)
                sleep(0.1)
            print("file completed.")  # noqa: T201


@override_settings(
    CONSUMER_INOTIFY_DELAY=0.01,
)
class TestConsumer(DirectoriesMixin, ConsumerThreadMixin, TransactionTestCase):
    def test_consume_file(self):
        self.t_start()

        f = Path(os.path.join(self.dirs.consumption_dir, "my_file.pdf"))
        shutil.copy(self.sample_file, f)

        self.wait_for_task_mock_call()

        self.consume_file_mock.assert_called_once()

        input_doc, _ = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file, f)

    def test_consume_file_invalid_ext(self):
        self.t_start()

        f = os.path.join(self.dirs.consumption_dir, "my_file.wow")
        shutil.copy(self.sample_file, f)

        self.wait_for_task_mock_call()

        self.consume_file_mock.assert_not_called()

    def test_consume_existing_file(self):
        f = Path(os.path.join(self.dirs.consumption_dir, "my_file.pdf"))
        shutil.copy(self.sample_file, f)

        self.t_start()
        self.consume_file_mock.assert_called_once()

        input_doc, _ = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file, f)

    @mock.patch("documents.management.commands.document_consumer.logger.error")
    def test_slow_write_pdf(self, error_logger):
        self.consume_file_mock.side_effect = self.bogus_task

        self.t_start()

        fname = Path(os.path.join(self.dirs.consumption_dir, "my_file.pdf"))

        self.slow_write_file(fname)

        self.wait_for_task_mock_call()

        error_logger.assert_not_called()

        self.consume_file_mock.assert_called_once()

        input_doc, _ = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file, fname)

    @mock.patch("documents.management.commands.document_consumer.logger.error")
    def test_slow_write_and_move(self, error_logger):
        self.consume_file_mock.side_effect = self.bogus_task

        self.t_start()

        fname = Path(os.path.join(self.dirs.consumption_dir, "my_file.~df"))
        fname2 = Path(os.path.join(self.dirs.consumption_dir, "my_file.pdf"))

        self.slow_write_file(fname)
        shutil.move(fname, fname2)

        self.wait_for_task_mock_call()

        self.consume_file_mock.assert_called_once()

        input_doc, _ = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file, fname2)

        error_logger.assert_not_called()

    @mock.patch("documents.management.commands.document_consumer.logger.error")
    def test_slow_write_incomplete(self, error_logger):
        self.consume_file_mock.side_effect = self.bogus_task

        self.t_start()

        fname = Path(os.path.join(self.dirs.consumption_dir, "my_file.pdf"))
        self.slow_write_file(fname, incomplete=True)

        self.wait_for_task_mock_call()

        self.consume_file_mock.assert_called_once()

        input_doc, _ = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file, fname)

        # assert that we have an error logged with this invalid file.
        error_logger.assert_called_once()

    @override_settings(CONSUMPTION_DIR="does_not_exist")
    def test_consumption_directory_invalid(self):
        self.assertRaises(CommandError, call_command, "document_consumer", "--oneshot")

    @override_settings(CONSUMPTION_DIR="")
    def test_consumption_directory_unset(self):
        self.assertRaises(CommandError, call_command, "document_consumer", "--oneshot")

    def test_mac_write(self):
        self.consume_file_mock.side_effect = self.bogus_task

        self.t_start()

        shutil.copy(
            self.sample_file,
            os.path.join(self.dirs.consumption_dir, ".DS_STORE"),
        )
        shutil.copy(
            self.sample_file,
            os.path.join(self.dirs.consumption_dir, "my_file.pdf"),
        )
        shutil.copy(
            self.sample_file,
            os.path.join(self.dirs.consumption_dir, "._my_file.pdf"),
        )
        shutil.copy(
            self.sample_file,
            os.path.join(self.dirs.consumption_dir, "my_second_file.pdf"),
        )
        shutil.copy(
            self.sample_file,
            os.path.join(self.dirs.consumption_dir, "._my_second_file.pdf"),
        )

        sleep(5)

        self.wait_for_task_mock_call(expected_call_count=2)

        self.assertEqual(2, self.consume_file_mock.call_count)

        consumed_files = []
        for input_doc, _ in self.get_all_consume_delay_call_args():
            consumed_files.append(input_doc.original_file.name)

        self.assertCountEqual(consumed_files, ["my_file.pdf", "my_second_file.pdf"])

    def test_is_ignored(self):
        test_paths = [
            {
                "path": os.path.join(self.dirs.consumption_dir, "foo.pdf"),
                "ignore": False,
            },
            {
                "path": os.path.join(self.dirs.consumption_dir, "foo", "bar.pdf"),
                "ignore": False,
            },
            {
                "path": os.path.join(self.dirs.consumption_dir, ".DS_STORE"),
                "ignore": True,
            },
            {
                "path": os.path.join(self.dirs.consumption_dir, ".DS_Store"),
                "ignore": True,
            },
            {
                "path": os.path.join(self.dirs.consumption_dir, ".stfolder", "foo.pdf"),
                "ignore": True,
            },
            {
                "path": os.path.join(self.dirs.consumption_dir, ".stfolder.pdf"),
                "ignore": False,
            },
            {
                "path": os.path.join(
                    self.dirs.consumption_dir,
                    ".stversions",
                    "foo.pdf",
                ),
                "ignore": True,
            },
            {
                "path": os.path.join(self.dirs.consumption_dir, ".stversions.pdf"),
                "ignore": False,
            },
            {
                "path": os.path.join(self.dirs.consumption_dir, "._foo.pdf"),
                "ignore": True,
            },
            {
                "path": os.path.join(self.dirs.consumption_dir, "my_foo.pdf"),
                "ignore": False,
            },
            {
                "path": os.path.join(self.dirs.consumption_dir, "._foo", "bar.pdf"),
                "ignore": True,
            },
            {
                "path": os.path.join(
                    self.dirs.consumption_dir,
                    "@eaDir",
                    "SYNO@.fileindexdb",
                    "_1jk.fnm",
                ),
                "ignore": True,
            },
        ]
        for test_setup in test_paths:
            filepath = test_setup["path"]
            expected_ignored_result = test_setup["ignore"]
            self.assertEqual(
                expected_ignored_result,
                document_consumer._is_ignored(filepath),
                f'_is_ignored("{filepath}") != {expected_ignored_result}',
            )

    @mock.patch("documents.management.commands.document_consumer.open")
    def test_consume_file_busy(self, open_mock):
        # Calling this mock always raises this
        open_mock.side_effect = OSError

        self.t_start()

        f = os.path.join(self.dirs.consumption_dir, "my_file.pdf")
        shutil.copy(self.sample_file, f)

        self.wait_for_task_mock_call()

        self.consume_file_mock.assert_not_called()


@override_settings(
    CONSUMER_POLLING=1,
    # please leave the delay here and down below
    # see https://github.com/paperless-ngx/paperless-ngx/pull/66
    CONSUMER_POLLING_DELAY=3,
    CONSUMER_POLLING_RETRY_COUNT=20,
)
class TestConsumerPolling(TestConsumer):
    # just do all the tests with polling
    pass


@override_settings(CONSUMER_INOTIFY_DELAY=0.01, CONSUMER_RECURSIVE=True)
class TestConsumerRecursive(TestConsumer):
    # just do all the tests with recursive
    pass


@override_settings(
    CONSUMER_RECURSIVE=True,
    CONSUMER_POLLING=1,
    CONSUMER_POLLING_DELAY=3,
    CONSUMER_POLLING_RETRY_COUNT=20,
)
class TestConsumerRecursivePolling(TestConsumer):
    # just do all the tests with polling and recursive
    pass


class TestConsumerTags(DirectoriesMixin, ConsumerThreadMixin, TransactionTestCase):
    @override_settings(CONSUMER_RECURSIVE=True, CONSUMER_SUBDIRS_AS_TAGS=True)
    def test_consume_file_with_path_tags(self):
        tag_names = ("existingTag", "Space Tag")
        # Create a Tag prior to consuming a file using it in path
        tag_ids = [
            Tag.objects.create(name="existingtag").pk,
        ]

        self.t_start()

        path = os.path.join(self.dirs.consumption_dir, *tag_names)
        os.makedirs(path, exist_ok=True)
        f = Path(os.path.join(path, "my_file.pdf"))
        # Wait at least inotify read_delay for recursive watchers
        # to be created for the new directories
        sleep(1)
        shutil.copy(self.sample_file, f)

        self.wait_for_task_mock_call()

        self.consume_file_mock.assert_called_once()

        # Add the pk of the Tag created by _consume()
        tag_ids.append(Tag.objects.get(name=tag_names[1]).pk)

        input_doc, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file, f)

        # assertCountEqual has a bad name, but test that the first
        # sequence contains the same elements as second, regardless of
        # their order.
        self.assertCountEqual(overrides.tag_ids, tag_ids)

    @override_settings(
        CONSUMER_POLLING=1,
        CONSUMER_POLLING_DELAY=3,
        CONSUMER_POLLING_RETRY_COUNT=20,
    )
    def test_consume_file_with_path_tags_polling(self):
        self.test_consume_file_with_path_tags()
