import logging
import os
from concurrent.futures import ThreadPoolExecutor
from fnmatch import filter
from pathlib import Path
from pathlib import PurePath
from threading import Event
from time import monotonic
from time import sleep
from typing import Final

from django import db
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from documents.data_models import ConsumableDocument
from documents.data_models import DocumentMetadataOverrides
from documents.data_models import DocumentSource
from documents.models import Tag
from documents.parsers import is_file_ext_supported
from documents.tasks import consume_file

try:
    from inotifyrecursive import INotify
    from inotifyrecursive import flags
except ImportError:  # pragma: no cover
    INotify = flags = None

logger = logging.getLogger("paperless.management.consumer")


def _tags_from_path(filepath) -> list[int]:
    """
    Walk up the directory tree from filepath to CONSUMPTION_DIR
    and get or create Tag IDs for every directory.

    Returns set of Tag models
    """
    db.close_old_connections()
    tag_ids = set()
    path_parts = Path(filepath).relative_to(settings.CONSUMPTION_DIR).parent.parts
    for part in path_parts:
        tag_ids.add(
            Tag.objects.get_or_create(name__iexact=part, defaults={"name": part})[0].pk,
        )

    return list(tag_ids)


def _is_ignored(filepath: str) -> bool:
    """
    Checks if the given file should be ignored, based on configured
    patterns.

    Returns True if the file is ignored, False otherwise
    """
    filepath = os.path.abspath(
        os.path.normpath(filepath),
    )

    # Trim out the consume directory, leaving only filename and it's
    # path relative to the consume directory
    filepath_relative = PurePath(filepath).relative_to(settings.CONSUMPTION_DIR)

    # March through the components of the path, including directories and the filename
    # looking for anything matching
    # foo/bar/baz/file.pdf -> (foo, bar, baz, file.pdf)
    parts = []
    for part in filepath_relative.parts:
        # If the part is not the name (ie, it's a dir)
        # Need to append the trailing slash or fnmatch doesn't match
        # fnmatch("dir", "dir/*") == False
        # fnmatch("dir/", "dir/*") == True
        if part != filepath_relative.name:
            part = part + "/"
        parts.append(part)

    for pattern in settings.CONSUMER_IGNORE_PATTERNS:
        if len(filter(parts, pattern)):
            return True

    return False


def _consume(filepath: str) -> None:
    if os.path.isdir(filepath) or _is_ignored(filepath):
        return

    if not os.path.isfile(filepath):
        logger.debug(f"Not consuming file {filepath}: File has moved.")
        return

    if not is_file_ext_supported(os.path.splitext(filepath)[1]):
        logger.warning(f"Not consuming file {filepath}: Unknown file extension.")
        return

    # Total wait time: up to 500ms
    os_error_retry_count: Final[int] = 50
    os_error_retry_wait: Final[float] = 0.01

    read_try_count = 0
    file_open_ok = False
    os_error_str = None

    while (read_try_count < os_error_retry_count) and not file_open_ok:
        try:
            with open(filepath, "rb"):
                file_open_ok = True
        except OSError as e:
            read_try_count += 1
            os_error_str = str(e)
            sleep(os_error_retry_wait)

    if read_try_count >= os_error_retry_count:
        logger.warning(f"Not consuming file {filepath}: OS reports {os_error_str}")
        return

    tag_ids = None
    try:
        if settings.CONSUMER_SUBDIRS_AS_TAGS:
            tag_ids = _tags_from_path(filepath)
    except Exception:
        logger.exception("Error creating tags from path")

    try:
        logger.info(f"Adding {filepath} to the task queue.")
        consume_file.delay(
            ConsumableDocument(
                source=DocumentSource.ConsumeFolder,
                original_file=filepath,
            ),
            DocumentMetadataOverrides(tag_ids=tag_ids),
        )
    except Exception:
        # Catch all so that the consumer won't crash.
        # This is also what the test case is listening for to check for
        # errors.
        logger.exception("Error while consuming document")


def _consume_wait_unmodified(file: str) -> None:
    """
    Waits for the given file to appear unmodified based on file size
    and modification time.  Will wait a configured number of seconds
    and retry a configured number of times before either consuming or
    giving up
    """
    if _is_ignored(file):
        return

    logger.debug(f"Waiting for file {file} to remain unmodified")
    mtime = -1
    size = -1
    current_try = 0
    while current_try < settings.CONSUMER_POLLING_RETRY_COUNT:
        try:
            stat_data = os.stat(file)
            new_mtime = stat_data.st_mtime
            new_size = stat_data.st_size
        except FileNotFoundError:
            logger.debug(
                f"File {file} moved while waiting for it to remain unmodified.",
            )
            return
        if new_mtime == mtime and new_size == size:
            _consume(file)
            return
        mtime = new_mtime
        size = new_size
        sleep(settings.CONSUMER_POLLING_DELAY)
        current_try += 1

    logger.error(f"Timeout while waiting on file {file} to remain unmodified.")


class Handler(FileSystemEventHandler):
    def __init__(self, pool: ThreadPoolExecutor) -> None:
        super().__init__()
        self._pool = pool

    def on_created(self, event):
        self._pool.submit(_consume_wait_unmodified, event.src_path)

    def on_moved(self, event):
        self._pool.submit(_consume_wait_unmodified, event.dest_path)


class Command(BaseCommand):
    """
    On every iteration of an infinite loop, consume what we can from the
    consumption directory.
    """

    # This is here primarily for the tests and is irrelevant in production.
    stop_flag = Event()
    # Also only for testing, configures in one place the timeout used before checking
    # the stop flag
    testing_timeout_s: Final[float] = 0.5
    testing_timeout_ms: Final[float] = testing_timeout_s * 1000.0

    def add_arguments(self, parser):
        parser.add_argument(
            "directory",
            default=settings.CONSUMPTION_DIR,
            nargs="?",
            help="The consumption directory.",
        )
        parser.add_argument("--oneshot", action="store_true", help="Run only once.")

        # Only use during unit testing, will configure a timeout
        # Leaving it unset or false and the consumer will exit when it
        # receives SIGINT
        parser.add_argument(
            "--testing",
            action="store_true",
            help="Flag used only for unit testing",
            default=False,
        )

    def handle(self, *args, **options):
        directory = options["directory"]
        recursive = settings.CONSUMER_RECURSIVE

        if not directory:
            raise CommandError("CONSUMPTION_DIR does not appear to be set.")

        directory = os.path.abspath(directory)

        if not os.path.isdir(directory):
            raise CommandError(f"Consumption directory {directory} does not exist")

        # Consumer will need this
        settings.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

        if recursive:
            for dirpath, _, filenames in os.walk(directory):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    _consume(filepath)
        else:
            for entry in os.scandir(directory):
                _consume(entry.path)

        if options["oneshot"]:
            return

        if settings.CONSUMER_POLLING == 0 and INotify:
            self.handle_inotify(directory, recursive, is_testing=options["testing"])
        else:
            if INotify is None and settings.CONSUMER_POLLING == 0:  # pragma: no cover
                logger.warning("Using polling as INotify import failed")
            self.handle_polling(directory, recursive, is_testing=options["testing"])

        logger.debug("Consumer exiting.")

    def handle_polling(self, directory, recursive, *, is_testing: bool):
        logger.info(f"Polling directory for changes: {directory}")

        timeout = None
        if is_testing:
            timeout = self.testing_timeout_s
            logger.debug(f"Configuring timeout to {timeout}s")

        polling_interval = settings.CONSUMER_POLLING
        if polling_interval == 0:  # pragma: no cover
            # Only happens if INotify failed to import
            logger.warning("Using polling of 10s, consider setting this")
            polling_interval = 10

        with ThreadPoolExecutor(max_workers=4) as pool:
            observer = PollingObserver(timeout=polling_interval)
            observer.schedule(Handler(pool), directory, recursive=recursive)
            observer.start()
            try:
                while observer.is_alive():
                    observer.join(timeout)
                    if self.stop_flag.is_set():
                        observer.stop()
            except KeyboardInterrupt:
                observer.stop()
            observer.join()

    def handle_inotify(self, directory, recursive, *, is_testing: bool):
        logger.info(f"Using inotify to watch directory for changes: {directory}")

        timeout_ms = None
        if is_testing:
            timeout_ms = self.testing_timeout_ms
            logger.debug(f"Configuring timeout to {timeout_ms}ms")

        inotify = INotify()
        inotify_flags = flags.CLOSE_WRITE | flags.MOVED_TO | flags.MODIFY
        if recursive:
            descriptor = inotify.add_watch_recursive(directory, inotify_flags)
        else:
            descriptor = inotify.add_watch(directory, inotify_flags)

        inotify_debounce_secs: Final[float] = settings.CONSUMER_INOTIFY_DELAY
        inotify_debounce_ms: Final[int] = inotify_debounce_secs * 1000

        finished = False

        notified_files = {}

        while not finished:
            try:
                for event in inotify.read(timeout=timeout_ms):
                    path = inotify.get_path(event.wd) if recursive else directory
                    filepath = os.path.join(path, event.name)
                    if flags.MODIFY in flags.from_mask(event.mask):
                        notified_files.pop(filepath, None)
                    else:
                        notified_files[filepath] = monotonic()

                # Check the files against the timeout
                still_waiting = {}
                # last_event_time is time of the last inotify event for this file
                for filepath, last_event_time in notified_files.items():
                    # Current time - last time over the configured timeout
                    waited_long_enough = (
                        monotonic() - last_event_time
                    ) > inotify_debounce_secs

                    # Also make sure the file exists still, some scanners might write a
                    # temporary file first
                    file_still_exists = os.path.exists(filepath) and os.path.isfile(
                        filepath,
                    )

                    if waited_long_enough and file_still_exists:
                        _consume(filepath)
                    elif file_still_exists:
                        still_waiting[filepath] = last_event_time

                # These files are still waiting to hit the timeout
                notified_files = still_waiting

                # If files are waiting, need to exit read() to check them
                # Otherwise, go back to infinite sleep time, but only if not testing
                if len(notified_files) > 0:
                    timeout_ms = inotify_debounce_ms
                elif is_testing:
                    timeout_ms = self.testing_timeout_ms
                else:
                    timeout_ms = None

                if self.stop_flag.is_set():
                    logger.debug("Finishing because event is set")
                    finished = True

            except KeyboardInterrupt:
                logger.info("Received SIGINT, stopping inotify")
                finished = True

        inotify.rm_watch(descriptor)
        inotify.close()
