import dataclasses
import email.contentmanager
import random
import uuid
from collections import namedtuple
from contextlib import AbstractContextManager
from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import DatabaseError
from django.test import TestCase
from django.utils import timezone
from imap_tools import NOT
from imap_tools import EmailAddress
from imap_tools import FolderInfo
from imap_tools import MailboxFolderSelectError
from imap_tools import MailboxLoginError
from imap_tools import MailMessage
from imap_tools import MailMessageFlags
from imap_tools import errors
from rest_framework import status
from rest_framework.test import APITestCase

from documents.models import Correspondent
from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import FileSystemAssertsMixin
from paperless_mail import tasks
from paperless_mail.mail import MailAccountHandler
from paperless_mail.mail import MailError
from paperless_mail.mail import TagMailAction
from paperless_mail.mail import apply_mail_action
from paperless_mail.models import MailAccount
from paperless_mail.models import MailRule
from paperless_mail.models import ProcessedMail


@dataclasses.dataclass
class _AttachmentDef:
    filename: str = "a_file.pdf"
    maintype: str = "application/pdf"
    subtype: str = "pdf"
    disposition: str = "attachment"
    content: bytes = b"a PDF document"


class BogusFolderManager:
    current_folder = "INBOX"

    def set(self, new_folder):
        if new_folder not in ["INBOX", "spam"]:
            raise MailboxFolderSelectError(None, "uhm")
        self.current_folder = new_folder


class BogusClient:
    def __init__(self, messages):
        self.messages: list[MailMessage] = messages
        self.capabilities: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def authenticate(self, mechanism, authobject):
        # authobject must be a callable object
        auth_bytes = authobject(None)
        if auth_bytes != b"\x00admin\x00w57\xc3\xa4\xc3\xb6\xc3\xbcw4b6huwb6nhu":
            raise MailboxLoginError("BAD", "OK")

    def uid(self, command, *args):
        if command == "STORE":
            for message in self.messages:
                if message.uid == args[0]:
                    flag = args[2]
                    if flag == "processed":
                        message._raw_flag_data.append(b"+FLAGS (processed)")
                        MailMessage.flags.fget.cache_clear()


class BogusMailBox(AbstractContextManager):
    # Common values so tests don't need to remember an accepted login
    USERNAME: str = "admin"
    ASCII_PASSWORD: str = "secret"
    # Note the non-ascii characters here
    UTF_PASSWORD: str = "w57äöüw4b6huwb6nhu"
    # A dummy access token
    ACCESS_TOKEN = "ea7e075cd3acf2c54c48e600398d5d5a"

    def __init__(self):
        self.messages: list[MailMessage] = []
        self.messages_spam: list[MailMessage] = []
        self.folder = BogusFolderManager()
        self.client = BogusClient(self.messages)
        self._host = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def updateClient(self):
        self.client = BogusClient(self.messages)

    def login(self, username, password):
        # This will raise a UnicodeEncodeError if the password is not ASCII only
        password.encode("ascii")
        # Otherwise, check for correct values
        if username != self.USERNAME or password != self.ASCII_PASSWORD:
            raise MailboxLoginError("BAD", "OK")

    def login_utf8(self, username, password):
        # Expected to only be called with the UTF-8 password
        if username != self.USERNAME or password != self.UTF_PASSWORD:
            raise MailboxLoginError("BAD", "OK")

    def xoauth2(self, username: str, access_token: str):
        if username != self.USERNAME or access_token != self.ACCESS_TOKEN:
            raise MailboxLoginError("BAD", "OK")

    def fetch(self, criteria, mark_seen, charset="", *, bulk=True):
        msg = self.messages

        criteria = str(criteria).strip("()").split(" ")

        if "UNSEEN" in criteria:
            msg = filter(lambda m: not m.seen, msg)

        if "SUBJECT" in criteria:
            subject = criteria[criteria.index("SUBJECT") + 1].strip('"')
            msg = filter(lambda m: subject in m.subject, msg)

        if "BODY" in criteria:
            body = criteria[criteria.index("BODY") + 1].strip('"')
            msg = filter(lambda m: body in m.text, msg)

        if "FROM" in criteria:
            from_ = criteria[criteria.index("FROM") + 1].strip('"')
            msg = filter(lambda m: from_ in m.from_, msg)

        if "TO" in criteria:
            to_ = criteria[criteria.index("TO") + 1].strip('"')
            msg = []
            for m in self.messages:
                for to_addrs in m.to:
                    if to_ in to_addrs:
                        msg.append(m)

        if "UNFLAGGED" in criteria:
            msg = filter(lambda m: not m.flagged, msg)

        if "UNKEYWORD" in criteria:
            tag = criteria[criteria.index("UNKEYWORD") + 1].strip("'")
            msg = filter(lambda m: tag not in m.flags, msg)

        if "(X-GM-LABELS" in criteria:  # ['NOT', '(X-GM-LABELS', '"processed"']
            msg = filter(lambda m: "processed" not in m.flags, msg)

        return list(msg)

    def delete(self, uid_list):
        self.messages = list(filter(lambda m: m.uid not in uid_list, self.messages))

    def flag(self, uid_list, flag_set, value):
        for message in self.messages:
            if message.uid in uid_list:
                for flag in flag_set:
                    if flag == MailMessageFlags.FLAGGED:
                        message.flagged = value
                    if flag == MailMessageFlags.SEEN:
                        message.seen = value
                    if flag == "processed":
                        message._raw_flag_data.append(b"+FLAGS (processed)")
                        MailMessage.flags.fget.cache_clear()

    def move(self, uid_list, folder):
        if folder == "spam":
            self.messages_spam += list(
                filter(lambda m: m.uid in uid_list, self.messages),
            )
            self.messages = list(filter(lambda m: m.uid not in uid_list, self.messages))
        else:
            raise Exception


def fake_magic_from_buffer(buffer, *, mime=False):
    if mime:
        if "PDF" in str(buffer):
            return "application/pdf"
        else:
            return "unknown/type"
    else:
        return "Some verbose file description"


class MessageBuilder:
    def __init__(self):
        self._used_uids = set()

    def create_message(
        self,
        *,
        attachments: int | list[_AttachmentDef] = 1,
        body: str = "",
        subject: str = "the subject",
        from_: str = "no_one@mail.com",
        to: list[str] | None = None,
        seen: bool = False,
        flagged: bool = False,
        processed: bool = False,
    ) -> MailMessage:
        if to is None:
            to = ["tosomeone@somewhere.com"]

        email_msg = email.message.EmailMessage()
        # TODO: This does NOT set the UID
        email_msg["Message-ID"] = str(uuid.uuid4())
        email_msg["Subject"] = subject
        email_msg["From"] = from_
        email_msg["To"] = str(" ,".join(to))
        email_msg.set_content(body)

        # Either add some default number of attachments
        # or the provided attachments
        if isinstance(attachments, int):
            for i in range(attachments):
                attachment = _AttachmentDef(filename=f"file_{i}.pdf")
                email_msg.add_attachment(
                    attachment.content,
                    maintype=attachment.maintype,
                    subtype=attachment.subtype,
                    disposition=attachment.disposition,
                    filename=attachment.filename,
                )
        else:
            for attachment in attachments:
                email_msg.add_attachment(
                    attachment.content,
                    maintype=attachment.maintype,
                    subtype=attachment.subtype,
                    disposition=attachment.disposition,
                    filename=attachment.filename,
                )

        # Convert the EmailMessage to an imap_tools MailMessage
        imap_msg = MailMessage.from_bytes(email_msg.as_bytes())

        # TODO: Unsure how to add a uid to the actual EmailMessage. This hacks it in,
        #  based on how imap_tools uses regex to extract it.
        #  This should be a large enough pool
        uid = random.randint(1, 10000)
        while uid in self._used_uids:
            uid = random.randint(1, 10000)
        self._used_uids.add(uid)

        imap_msg._raw_uid_data = f"UID {uid}".encode()

        imap_msg.seen = seen
        imap_msg.flagged = flagged
        if processed:
            imap_msg._raw_flag_data.append(b"+FLAGS (processed)")
            MailMessage.flags.fget.cache_clear()

        return imap_msg


def reset_bogus_mailbox(bogus_mailbox: BogusMailBox, message_builder: MessageBuilder):
    bogus_mailbox.messages = []
    bogus_mailbox.messages_spam = []
    bogus_mailbox.messages.append(
        message_builder.create_message(
            subject="Invoice 1",
            from_="amazon@amazon.de",
            to=["me@myselfandi.com", "helpdesk@mydomain.com"],
            body="cables",
            seen=True,
            flagged=False,
            processed=False,
        ),
    )
    bogus_mailbox.messages.append(
        message_builder.create_message(
            subject="Invoice 2",
            body="from my favorite electronic store",
            to=["invoices@mycompany.com"],
            seen=False,
            flagged=True,
            processed=True,
        ),
    )
    bogus_mailbox.messages.append(
        message_builder.create_message(
            subject="Claim your $10M price now!",
            from_="amazon@amazon-some-indian-site.org",
            to=["special@me.me"],
            seen=False,
        ),
    )
    bogus_mailbox.updateClient()


class MailMocker(DirectoriesMixin, FileSystemAssertsMixin, TestCase):
    def setUp(self):
        self.bogus_mailbox = BogusMailBox()
        self.messageBuilder = MessageBuilder()

        reset_bogus_mailbox(self.bogus_mailbox, self.messageBuilder)

        patcher = mock.patch("paperless_mail.mail.MailBox")
        m = patcher.start()
        m.return_value = self.bogus_mailbox
        self.addCleanup(patcher.stop)

        patcher = mock.patch("paperless_mail.mail.queue_consumption_tasks")
        self._queue_consumption_tasks_mock = patcher.start()
        self.addCleanup(patcher.stop)

        super().setUp()

    def assert_queue_consumption_tasks_call_args(
        self,
        expected_call_args: list[list[dict[str, str]]],
    ):
        """
        Verifies that queue_consumption_tasks has been called with the expected arguments.

        expected_call_args is the following format:

        * List of calls to queue_consumption_tasks, called once per mail, where each element is:
        * List of signatures for the consume_file task, where each element is:
        * dictionary containing arguments that need to be present in the consume_file signature.

        """

        # assert number of calls to queue_consumption_tasks match
        self.assertEqual(
            len(self._queue_consumption_tasks_mock.call_args_list),
            len(expected_call_args),
        )

        for (mock_args, mock_kwargs), expected_signatures in zip(
            self._queue_consumption_tasks_mock.call_args_list,
            expected_call_args,
        ):
            consume_tasks = mock_kwargs["consume_tasks"]

            # assert number of consume_file tasks match
            self.assertEqual(len(consume_tasks), len(expected_signatures))

            for consume_task, expected_signature in zip(
                consume_tasks,
                expected_signatures,
            ):
                input_doc, overrides = consume_task.args

                # assert the file exists
                self.assertIsFile(input_doc.original_file)

                # assert all expected arguments are present in the signature
                for key, value in expected_signature.items():
                    if key == "override_correspondent_id":
                        self.assertEqual(overrides.correspondent_id, value)
                    elif key == "override_filename":
                        self.assertEqual(overrides.filename, value)
                    elif key == "override_title":
                        self.assertEqual(overrides.title, value)
                    else:
                        self.fail("No match for expected arg")

    def apply_mail_actions(self):
        """
        Applies pending actions to mails by inspecting calls to the queue_consumption_tasks method.
        """
        for args, kwargs in self._queue_consumption_tasks_mock.call_args_list:
            message = kwargs["message"]
            rule = kwargs["rule"]
            apply_mail_action([], rule.pk, message.uid, message.subject, message.date)


@mock.patch("paperless_mail.mail.magic.from_buffer", fake_magic_from_buffer)
class TestMail(
    DirectoriesMixin,
    FileSystemAssertsMixin,
    TestCase,
):
    def setUp(self):
        self.mailMocker = MailMocker()
        self.mailMocker.setUp()
        self.mail_account_handler = MailAccountHandler()

        super().setUp()

    def test_get_correspondent(self):
        message = namedtuple("MailMessage", [])
        message.from_ = "someone@somewhere.com"
        message.from_values = EmailAddress(
            "Someone!",
            "someone@somewhere.com",
        )

        message2 = namedtuple("MailMessage", [])
        message2.from_ = "me@localhost.com"
        message2.from_values = EmailAddress(
            "",
            "fake@localhost.com",
        )

        me_localhost = Correspondent.objects.create(name=message2.from_)
        someone_else = Correspondent.objects.create(name="someone else")

        handler = MailAccountHandler()

        rule = MailRule(
            name="a",
            assign_correspondent_from=MailRule.CorrespondentSource.FROM_NOTHING,
        )
        self.assertIsNone(handler._get_correspondent(message, rule))

        rule = MailRule(
            name="b",
            assign_correspondent_from=MailRule.CorrespondentSource.FROM_EMAIL,
        )
        c = handler._get_correspondent(message, rule)
        self.assertIsNotNone(c)
        self.assertEqual(c.name, "someone@somewhere.com")
        c = handler._get_correspondent(message2, rule)
        self.assertIsNotNone(c)
        self.assertEqual(c.name, "me@localhost.com")
        self.assertEqual(c.id, me_localhost.id)

        rule = MailRule(
            name="c",
            assign_correspondent_from=MailRule.CorrespondentSource.FROM_NAME,
        )
        c = handler._get_correspondent(message, rule)
        self.assertIsNotNone(c)
        self.assertEqual(c.name, "Someone!")
        c = handler._get_correspondent(message2, rule)
        self.assertIsNotNone(c)
        self.assertEqual(c.id, me_localhost.id)

        rule = MailRule(
            name="d",
            assign_correspondent_from=MailRule.CorrespondentSource.FROM_CUSTOM,
            assign_correspondent=someone_else,
        )
        c = handler._get_correspondent(message, rule)
        self.assertEqual(c, someone_else)

    def test_get_title(self):
        message = namedtuple("MailMessage", [])
        message.subject = "the message title"
        att = namedtuple("Attachment", [])
        att.filename = "this_is_the_file.pdf"

        handler = MailAccountHandler()

        rule = MailRule(
            name="a",
            assign_title_from=MailRule.TitleSource.FROM_FILENAME,
        )
        self.assertEqual(handler._get_title(message, att, rule), "this_is_the_file")
        rule = MailRule(
            name="b",
            assign_title_from=MailRule.TitleSource.FROM_SUBJECT,
        )
        self.assertEqual(handler._get_title(message, att, rule), "the message title")
        rule = MailRule(
            name="b",
            assign_title_from=MailRule.TitleSource.NONE,
        )
        self.assertEqual(handler._get_title(message, att, rule), None)

    def test_handle_message(self):
        message = self.mailMocker.messageBuilder.create_message(
            subject="the message title",
            from_="Myself",
            attachments=2,
        )

        account = MailAccount.objects.create()
        rule = MailRule(
            assign_title_from=MailRule.TitleSource.FROM_FILENAME,
            account=account,
        )
        rule.save()

        result = self.mail_account_handler._handle_message(message, rule)

        self.assertEqual(result, 2)

        self.mailMocker._queue_consumption_tasks_mock.assert_called()

        self.mailMocker.assert_queue_consumption_tasks_call_args(
            [
                [
                    {"override_title": "file_0", "override_filename": "file_0.pdf"},
                    {"override_title": "file_1", "override_filename": "file_1.pdf"},
                ],
            ],
        )

    def test_handle_empty_message(self):
        message = namedtuple("MailMessage", [])

        message.attachments = []
        rule = MailRule()

        result = self.mail_account_handler._handle_message(message, rule)

        self.mailMocker._queue_consumption_tasks_mock.assert_not_called()
        self.assertEqual(result, 0)

    def test_handle_unknown_mime_type(self):
        message = self.mailMocker.messageBuilder.create_message(
            attachments=[
                _AttachmentDef(filename="f1.pdf"),
                _AttachmentDef(
                    filename="f2.json",
                    content=b"{'much': 'payload.', 'so': 'json', 'wow': true}",
                ),
            ],
        )

        account = MailAccount.objects.create()
        rule = MailRule(
            assign_title_from=MailRule.TitleSource.FROM_FILENAME,
            account=account,
        )
        rule.save()

        result = self.mail_account_handler._handle_message(message, rule)

        self.assertEqual(result, 1)
        self.mailMocker.assert_queue_consumption_tasks_call_args(
            [
                [
                    {"override_filename": "f1.pdf"},
                ],
            ],
        )

    def test_handle_disposition(self):
        message = self.mailMocker.messageBuilder.create_message(
            attachments=[
                _AttachmentDef(
                    filename="f1.pdf",
                    disposition="inline",
                ),
                _AttachmentDef(filename="f2.pdf"),
            ],
        )

        account = MailAccount.objects.create()
        rule = MailRule(
            assign_title_from=MailRule.TitleSource.FROM_FILENAME,
            account=account,
        )
        rule.save()

        result = self.mail_account_handler._handle_message(message, rule)
        self.assertEqual(result, 1)
        self.mailMocker.assert_queue_consumption_tasks_call_args(
            [
                [
                    {"override_filename": "f2.pdf"},
                ],
            ],
        )

    def test_handle_inline_files(self):
        message = self.mailMocker.messageBuilder.create_message(
            attachments=[
                _AttachmentDef(
                    filename="f1.pdf",
                    disposition="inline",
                ),
                _AttachmentDef(filename="f2.pdf"),
            ],
        )

        account = MailAccount.objects.create()
        rule = MailRule(
            assign_title_from=MailRule.TitleSource.FROM_FILENAME,
            account=account,
            attachment_type=MailRule.AttachmentProcessing.EVERYTHING,
        )
        rule.save()

        result = self.mail_account_handler._handle_message(message, rule)
        self.assertEqual(result, 2)
        self.mailMocker.assert_queue_consumption_tasks_call_args(
            [
                [
                    {"override_filename": "f1.pdf"},
                    {"override_filename": "f2.pdf"},
                ],
            ],
        )

    def test_filename_filter(self):
        """
        GIVEN:
            - Email with multiple similar named attachments
            - Rule with inclusive and exclusive filters
        WHEN:
            - Mail action filtering is checked
        THEN:
            - Mail action should not be performed for files excluded
            - Mail action should be performed for files included
        """
        message = self.mailMocker.messageBuilder.create_message(
            attachments=[
                _AttachmentDef(filename="f1.pdf"),
                _AttachmentDef(filename="f2.pdf"),
                _AttachmentDef(filename="f3.pdf"),
                _AttachmentDef(filename="f2.png"),
                _AttachmentDef(filename="file.PDf"),
                _AttachmentDef(filename="f1.Pdf"),
            ],
        )

        @dataclasses.dataclass(frozen=True)
        class FilterTestCase:
            name: str
            include_pattern: str | None
            exclude_pattern: str | None
            expected_matches: list[str]

        tests = [
            FilterTestCase(
                "PDF Wildcard",
                include_pattern="*.pdf",
                exclude_pattern=None,
                expected_matches=["f1.pdf", "f2.pdf", "f3.pdf", "file.PDf", "f1.Pdf"],
            ),
            FilterTestCase(
                "F1 PDF Only",
                include_pattern="f1.pdf",
                exclude_pattern=None,
                expected_matches=["f1.pdf", "f1.Pdf"],
            ),
            FilterTestCase(
                "All Files",
                include_pattern="*",
                exclude_pattern=None,
                expected_matches=[
                    "f1.pdf",
                    "f2.pdf",
                    "f3.pdf",
                    "f2.png",
                    "file.PDf",
                    "f1.Pdf",
                ],
            ),
            FilterTestCase(
                "PNG Only",
                include_pattern="*.png",
                exclude_pattern=None,
                expected_matches=["f2.png"],
            ),
            FilterTestCase(
                "PDF Files with f2 and f3",
                include_pattern="f2.pdf,f3*",
                exclude_pattern=None,
                expected_matches=["f2.pdf", "f3.pdf"],
            ),
            FilterTestCase(
                "PDF Files without f1",
                include_pattern="*.pdf",
                exclude_pattern="f1*",
                expected_matches=["f2.pdf", "f3.pdf", "file.PDf"],
            ),
            FilterTestCase(
                "PDF Files without f1 and f2",
                include_pattern="*.pdf",
                exclude_pattern="f1*,f2*",
                expected_matches=["f3.pdf", "file.PDf"],
            ),
            FilterTestCase(
                "PDF Files without f1 and f2 and f3",
                include_pattern="*.pdf",
                exclude_pattern="f1*,f2*,f3*",
                expected_matches=["file.PDf"],
            ),
            FilterTestCase(
                "All Files, no PNG",
                include_pattern="*",
                exclude_pattern="*.png",
                expected_matches=[
                    "f1.pdf",
                    "f2.pdf",
                    "f3.pdf",
                    "file.PDf",
                    "f1.Pdf",
                ],
            ),
        ]

        for test_case in tests:
            with self.subTest(msg=test_case.name):
                self.mailMocker._queue_consumption_tasks_mock.reset_mock()
                account = MailAccount(name=str(uuid.uuid4()))
                account.save()
                rule = MailRule(
                    name=str(uuid.uuid4()),
                    assign_title_from=MailRule.TitleSource.FROM_FILENAME,
                    account=account,
                    filter_attachment_filename_include=test_case.include_pattern,
                    filter_attachment_filename_exclude=test_case.exclude_pattern,
                )
                rule.save()

                self.mail_account_handler._handle_message(message, rule)
                self.mailMocker.assert_queue_consumption_tasks_call_args(
                    [
                        [{"override_filename": m} for m in test_case.expected_matches],
                    ],
                )

    @pytest.mark.flaky(reruns=4)
    def test_filename_filter_inline_no_consumption(self):
        """
        GIVEN:
            - Rule that processes all attachments but filters by filename
        WHEN:
            - Given email with inline attachment that does not meet filename filter
        THEN:
            - Mail action should not be performed
        """
        message = self.mailMocker.messageBuilder.create_message(
            attachments=[
                _AttachmentDef(
                    filename="test.png",
                    disposition="inline",
                ),
            ],
        )
        self.mailMocker.bogus_mailbox.messages.append(message)
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )
        account.save()
        rule = MailRule(
            name=str(uuid.uuid4()),
            assign_title_from=MailRule.TitleSource.FROM_FILENAME,
            account=account,
            filter_attachment_filename_include="*.pdf",
            attachment_type=MailRule.AttachmentProcessing.EVERYTHING,
            action=MailRule.MailAction.DELETE,
        )
        rule.save()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 4)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 1)

    def test_handle_mail_account_mark_read(self):
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MARK_READ,
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.fetch("UNSEEN", False)), 2)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.fetch("UNSEEN", False)), 0)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)

    def test_handle_mail_account_delete(self):
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.DELETE,
            filter_subject="Invoice",
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 1)

    def test_handle_mail_account_delete_no_filters(self):
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.DELETE,
            maximum_age=0,
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 0)

    @pytest.mark.flaky(reruns=4)
    def test_handle_mail_account_flag(self):
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.FLAG,
            filter_subject="Invoice",
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.assertEqual(
            len(self.mailMocker.bogus_mailbox.fetch("UNFLAGGED", False)),
            2,
        )

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(
            len(self.mailMocker.bogus_mailbox.fetch("UNFLAGGED", False)),
            1,
        )
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)

    @pytest.mark.flaky(reruns=4)
    def test_handle_mail_account_move(self):
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MOVE,
            action_parameter="spam",
            filter_subject="Claim",
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages_spam), 0)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 2)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages_spam), 1)

    def test_handle_mail_account_move_no_filters(self):
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MOVE,
            action_parameter="spam",
            maximum_age=0,
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages_spam), 0)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 0)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages_spam), 3)

    def test_handle_mail_account_tag(self):
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.TAG,
            action_parameter="processed",
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.assertEqual(
            len(self.mailMocker.bogus_mailbox.fetch("UNKEYWORD processed", False)),
            2,
        )

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.assertEqual(
            len(self.mailMocker.bogus_mailbox.fetch("UNKEYWORD processed", False)),
            0,
        )

    def test_handle_mail_account_tag_gmail(self):
        self.mailMocker.bogus_mailbox._host = "imap.gmail.com"
        self.mailMocker.bogus_mailbox.client.capabilities = ["X-GM-EXT-1"]

        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.TAG,
            action_parameter="processed",
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        criteria = NOT(gmail_label="processed")
        self.assertEqual(len(self.mailMocker.bogus_mailbox.fetch(criteria, False)), 2)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.fetch(criteria, False)), 0)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)

    def test_tag_mail_action_applemail_wrong_input(self):
        self.assertRaises(
            MailError,
            TagMailAction,
            "apple:black",
            False,
        )

    def test_handle_mail_account_tag_applemail(self):
        # all mails will be FLAGGED afterwards

        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.TAG,
            action_parameter="apple:green",
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.assertEqual(
            len(self.mailMocker.bogus_mailbox.fetch("UNFLAGGED", False)),
            2,
        )

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(
            len(self.mailMocker.bogus_mailbox.fetch("UNFLAGGED", False)),
            0,
        )
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)

    def test_error_login(self):
        """
        GIVEN:
            - Account configured with incorrect password
        WHEN:
            - Account tried to login
        THEN:
            - MailError with correct message raised
        """
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="wrong",
        )

        with self.assertRaisesRegex(
            MailError,
            "Error while authenticating account",
        ):
            self.mail_account_handler.handle_mail_account(account)

    @pytest.mark.flaky(reruns=4)
    def test_error_skip_account(self):
        _ = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="wroasdng",
        )

        account = MailAccount.objects.create(
            name="test2",
            imap_server="",
            username="admin",
            password="secret",
        )
        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MOVE,
            action_parameter="spam",
            filter_subject="Claim",
        )

        tasks.process_mail_accounts()
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 2)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages_spam), 1)

    def test_error_skip_rule(self):
        account = MailAccount.objects.create(
            name="test2",
            imap_server="",
            username="admin",
            password="secret",
        )
        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MOVE,
            action_parameter="spam",
            filter_subject="Claim",
            order=1,
            folder="uuuhhhh",
        )
        _ = MailRule.objects.create(
            name="testrule2",
            account=account,
            action=MailRule.MailAction.MOVE,
            action_parameter="spam",
            filter_subject="Claim",
            order=2,
        )

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 2)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages_spam), 1)

    def test_error_folder_set(self):
        """
        GIVEN:
            - Mail rule with non-existent folder
        THEN:
            - Should call list to output all folders in the account
            - Should not process any messages
        """
        account = MailAccount.objects.create(
            name="test2",
            imap_server="",
            username="admin",
            password="secret",
        )
        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MOVE,
            action_parameter="spam",
            filter_subject="Claim",
            order=1,
            folder="uuuhhhh",  # Invalid folder name
        )

        self.mailMocker.bogus_mailbox.folder.list = mock.Mock(
            return_value=[FolderInfo("SomeFoldername", "|", ())],
        )

        self.mail_account_handler.handle_mail_account(account)

        self.mailMocker.bogus_mailbox.folder.list.assert_called_once()
        self.mailMocker._queue_consumption_tasks_mock.assert_not_called()

    def test_error_folder_set_error_listing(self):
        """
        GIVEN:
            - Mail rule with non-existent folder
            - Mail account folder listing raises exception
        THEN:
            - Should not process any messages
        """
        account = MailAccount.objects.create(
            name="test2",
            imap_server="",
            username="admin",
            password="secret",
        )
        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MOVE,
            action_parameter="spam",
            filter_subject="Claim",
            order=1,
            folder="uuuhhhh",  # Invalid folder name
        )

        self.mailMocker.bogus_mailbox.folder.list = mock.Mock(
            side_effect=MailboxFolderSelectError(None, "uhm"),
        )

        self.mail_account_handler.handle_mail_account(account)

        self.mailMocker.bogus_mailbox.folder.list.assert_called_once()
        self.mailMocker._queue_consumption_tasks_mock.assert_not_called()

    @pytest.mark.flaky(reruns=4)
    @mock.patch("paperless_mail.mail.MailAccountHandler._get_correspondent")
    def test_error_skip_mail(self, m):
        def get_correspondent_fake(message, rule):
            if message.from_ == "amazon@amazon.de":
                raise ValueError("Does not compute.")
            else:
                return None

        m.side_effect = get_correspondent_fake

        account = MailAccount.objects.create(
            name="test2",
            imap_server="",
            username="admin",
            password="secret",
        )
        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MOVE,
            action_parameter="spam",
        )

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        # test that we still consume mail even if some mails throw errors.
        self.assertEqual(self.mailMocker._queue_consumption_tasks_mock.call_count, 2)

        # faulty mail still in inbox, untouched
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 1)
        self.assertEqual(
            self.mailMocker.bogus_mailbox.messages[0].from_,
            "amazon@amazon.de",
        )

    def test_error_create_correspondent(self):
        account = MailAccount.objects.create(
            name="test2",
            imap_server="",
            username="admin",
            password="secret",
        )
        _ = MailRule.objects.create(
            name="testrule",
            filter_from="amazon@amazon.de",
            account=account,
            action=MailRule.MailAction.MOVE,
            action_parameter="spam",
            assign_correspondent_from=MailRule.CorrespondentSource.FROM_EMAIL,
        )

        self.mail_account_handler.handle_mail_account(account)

        self.mailMocker._queue_consumption_tasks_mock.assert_called_once()

        c = Correspondent.objects.get(name="amazon@amazon.de")
        self.mailMocker.assert_queue_consumption_tasks_call_args(
            [
                [
                    {"override_correspondent_id": c.id},
                ],
            ],
        )

        self.mailMocker._queue_consumption_tasks_mock.reset_mock()
        reset_bogus_mailbox(
            self.mailMocker.bogus_mailbox,
            self.mailMocker.messageBuilder,
        )

        with mock.patch("paperless_mail.mail.Correspondent.objects.get_or_create") as m:
            m.side_effect = DatabaseError()

            self.mail_account_handler.handle_mail_account(account)

        self.mailMocker.assert_queue_consumption_tasks_call_args(
            [
                [
                    {"override_correspondent_id": None},
                ],
            ],
        )

    @pytest.mark.flaky(reruns=4)
    def test_filters(self):
        account = MailAccount.objects.create(
            name="test3",
            imap_server="",
            username="admin",
            password="secret",
        )

        for f_body, f_from, f_to, f_subject, expected_mail_count in [
            (None, None, None, "Claim", 1),
            ("electronic", None, None, None, 1),
            (None, "amazon", None, None, 2),
            ("cables", "amazon", None, "Invoice", 1),
            (None, None, "test@email.com", None, 0),
            (None, None, "invoices@mycompany.com", None, 1),
            ("electronic", None, "invoices@mycompany.com", None, 1),
            (None, "amazon", "me@myselfandi.com", None, 1),
        ]:
            with self.subTest(f_body=f_body, f_from=f_from, f_subject=f_subject):
                MailRule.objects.all().delete()
                _ = MailRule.objects.create(
                    name="testrule3",
                    account=account,
                    action=MailRule.MailAction.DELETE,
                    filter_subject=f_subject,
                    filter_body=f_body,
                    filter_from=f_from,
                    filter_to=f_to,
                )
                reset_bogus_mailbox(
                    self.mailMocker.bogus_mailbox,
                    self.mailMocker.messageBuilder,
                )
                self.mailMocker._queue_consumption_tasks_mock.reset_mock()

                self.mailMocker._queue_consumption_tasks_mock.assert_not_called()
                self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)

                self.mail_account_handler.handle_mail_account(account)
                self.mailMocker.apply_mail_actions()

                self.assertEqual(
                    len(self.mailMocker.bogus_mailbox.messages),
                    3 - expected_mail_count,
                )
                self.assertEqual(
                    self.mailMocker._queue_consumption_tasks_mock.call_count,
                    expected_mail_count,
                )

    def test_auth_plain_fallback(self):
        """
        GIVEN:
            - Mail account with password containing non-ASCII characters
        WHEN:
            - Mail account is handled
        THEN:
            - Should still authenticate to the mail account
        """
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username=BogusMailBox.USERNAME,
            # Note the non-ascii characters here
            password=BogusMailBox.UTF_PASSWORD,
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MARK_READ,
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.mailMocker._queue_consumption_tasks_mock.assert_not_called()
        self.assertEqual(len(self.mailMocker.bogus_mailbox.fetch("UNSEEN", False)), 2)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(self.mailMocker._queue_consumption_tasks_mock.call_count, 2)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.fetch("UNSEEN", False)), 0)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)

    def test_auth_plain_fallback_fails_still(self):
        """
        GIVEN:
            - Mail account with password containing non-ASCII characters
            - Incorrect password value
        WHEN:
            - Mail account is handled
        THEN:
            - Should raise a MailError for the account
        """
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username=BogusMailBox.USERNAME,
            # Note the non-ascii characters here
            # Passes the check in login, not in authenticate
            password="réception",
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MARK_READ,
        )

        self.assertRaises(
            MailError,
            self.mail_account_handler.handle_mail_account,
            account,
        )

    def test_auth_with_valid_token(self):
        """
        GIVEN:
            - Mail account configured with access token
        WHEN:
            - Mail account is handled
        THEN:
            - Should still authenticate to the mail account
        """
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username=BogusMailBox.USERNAME,
            # Note the non-ascii characters here
            password=BogusMailBox.ACCESS_TOKEN,
            is_token=True,
        )

        _ = MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MARK_READ,
        )

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.assertEqual(self.mailMocker._queue_consumption_tasks_mock.call_count, 0)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.fetch("UNSEEN", False)), 2)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(self.mailMocker._queue_consumption_tasks_mock.call_count, 2)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.fetch("UNSEEN", False)), 0)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)

    def test_disabled_rule(self):
        """
        GIVEN:
            - Mail rule is disabled
        WHEN:
            - Mail account is handled
        THEN:
            - Should not process any messages
        """
        account = MailAccount.objects.create(
            name="test",
            imap_server="",
            username="admin",
            password="secret",
        )
        MailRule.objects.create(
            name="testrule",
            account=account,
            action=MailRule.MailAction.MARK_READ,
            enabled=False,
        )

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()

        self.assertEqual(len(self.mailMocker.bogus_mailbox.messages), 3)
        self.assertEqual(len(self.mailMocker.bogus_mailbox.fetch("UNSEEN", False)), 2)

        self.mail_account_handler.handle_mail_account(account)
        self.mailMocker.apply_mail_actions()
        self.assertEqual(
            len(self.mailMocker.bogus_mailbox.fetch("UNSEEN", False)),
            2,
        )  # still 2


class TestPostConsumeAction(TestCase):
    def setUp(self):
        self.account = MailAccount.objects.create(
            name="test",
            imap_server="imap.test.com",
            imap_port=993,
            imap_security=MailAccount.ImapSecurity.SSL,
            username="testuser",
            password="password",
        )
        self.rule = MailRule.objects.create(
            name="testrule",
            account=self.account,
            action=MailRule.MailAction.MARK_READ,
            action_parameter="",
            folder="INBOX",
        )
        self.message_uid = "12345"
        self.message_subject = "Test Subject"
        self.message_date = timezone.make_aware(timezone.datetime(2023, 1, 1, 12, 0, 0))

    @mock.patch("paperless_mail.mail.get_mailbox")
    @mock.patch("paperless_mail.mail.mailbox_login")
    @mock.patch("paperless_mail.mail.get_rule_action")
    def test_post_consume_success(
        self,
        mock_get_rule_action,
        mock_mailbox_login,
        mock_get_mailbox,
    ):
        mock_mailbox = mock.MagicMock()
        mock_get_mailbox.return_value.__enter__.return_value = mock_mailbox
        mock_action = mock.MagicMock()
        mock_get_rule_action.return_value = mock_action

        apply_mail_action(
            result=[],
            rule_id=self.rule.pk,
            message_uid=self.message_uid,
            message_subject=self.message_subject,
            message_date=self.message_date,
        )

        mock_mailbox_login.assert_called_once_with(mock_mailbox, self.account)
        mock_mailbox.folder.set.assert_called_once_with(self.rule.folder)
        mock_action.post_consume.assert_called_once_with(
            mock_mailbox,
            self.message_uid,
            self.rule.action_parameter,
        )

        processed_mail = ProcessedMail.objects.get(uid=self.message_uid)
        self.assertEqual(processed_mail.status, "SUCCESS")

    @mock.patch("paperless_mail.mail.get_mailbox")
    @mock.patch("paperless_mail.mail.mailbox_login")
    @mock.patch("paperless_mail.mail.get_rule_action")
    def test_post_consume_failure(
        self,
        mock_get_rule_action,
        mock_mailbox_login,
        mock_get_mailbox,
    ):
        mock_mailbox = mock.MagicMock()
        mock_get_mailbox.return_value.__enter__.return_value = mock_mailbox
        mock_action = mock.MagicMock()
        mock_get_rule_action.return_value = mock_action
        mock_action.post_consume.side_effect = errors.ImapToolsError("Test Exception")

        with (
            self.assertRaises(errors.ImapToolsError),
            self.assertLogs("paperless.mail", level="ERROR") as cm,
        ):
            apply_mail_action(
                result=[],
                rule_id=self.rule.pk,
                message_uid=self.message_uid,
                message_subject=self.message_subject,
                message_date=self.message_date,
            )
            error_str = cm.output[0]
            expected_str = "Error while processing mail action during post_consume"
            self.assertIn(expected_str, error_str)

        processed_mail = ProcessedMail.objects.get(uid=self.message_uid)
        self.assertEqual(processed_mail.status, "FAILED")
        self.assertIn("Test Exception", processed_mail.error)


class TestManagementCommand(TestCase):
    @mock.patch(
        "paperless_mail.management.commands.mail_fetcher.tasks.process_mail_accounts",
    )
    def test_mail_fetcher(self, m):
        call_command("mail_fetcher")

        m.assert_called_once()


class TestTasks(TestCase):
    @mock.patch("paperless_mail.tasks.MailAccountHandler.handle_mail_account")
    def test_all_accounts(self, m):
        m.side_effect = lambda account: 6

        MailAccount.objects.create(
            name="A",
            imap_server="A",
            username="A",
            password="A",
        )
        MailAccount.objects.create(
            name="B",
            imap_server="A",
            username="A",
            password="A",
        )
        MailRule.objects.create(
            name="A",
            account=MailAccount.objects.get(name="A"),
        )
        MailRule.objects.create(
            name="B",
            account=MailAccount.objects.get(name="B"),
        )

        result = tasks.process_mail_accounts()

        self.assertEqual(m.call_count, 2)
        self.assertIn("Added 12", result)

        m.side_effect = lambda account: 0
        result = tasks.process_mail_accounts()
        self.assertIn("No new", result)

    @mock.patch("paperless_mail.tasks.MailAccountHandler.handle_mail_account")
    def test_accounts_no_enabled_rules(self, m):
        m.side_effect = lambda account: 6

        MailAccount.objects.create(
            name="A",
            imap_server="A",
            username="A",
            password="A",
        )
        MailAccount.objects.create(
            name="B",
            imap_server="A",
            username="A",
            password="A",
        )
        MailRule.objects.create(
            name="A",
            account=MailAccount.objects.get(name="A"),
            enabled=False,
        )
        MailRule.objects.create(
            name="B",
            account=MailAccount.objects.get(name="B"),
            enabled=False,
        )

        tasks.process_mail_accounts()
        self.assertEqual(m.call_count, 0)

    @mock.patch("paperless_mail.tasks.MailAccountHandler.handle_mail_account")
    def test_process_with_account_ids(self, m):
        m.side_effect = lambda account: 6

        account_a = MailAccount.objects.create(
            name="A",
            imap_server="A",
            username="A",
            password="A",
        )
        account_b = MailAccount.objects.create(
            name="B",
            imap_server="A",
            username="A",
            password="A",
        )
        MailRule.objects.create(
            name="A",
            account=account_a,
        )
        MailRule.objects.create(
            name="B",
            account=account_b,
        )

        result = tasks.process_mail_accounts(account_ids=[account_a.id])

        self.assertEqual(m.call_count, 1)
        self.assertIn("Added 6", result)

        m.side_effect = lambda account: 0
        result = tasks.process_mail_accounts(account_ids=[account_b.id])
        self.assertIn("No new", result)


class TestMailAccountTestView(APITestCase):
    def setUp(self):
        self.mailMocker = MailMocker()
        self.mailMocker.setUp()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpassword",
        )
        self.client.force_authenticate(user=self.user)
        self.url = "/api/mail_accounts/test/"

    def test_mail_account_test_view_success(self):
        data = {
            "imap_server": "imap.example.com",
            "imap_port": 993,
            "imap_security": MailAccount.ImapSecurity.SSL,
            "username": "admin",
            "password": "secret",
            "account_type": MailAccount.MailAccountType.IMAP,
            "is_token": False,
        }
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"success": True})

    def test_mail_account_test_view_mail_error(self):
        data = {
            "imap_server": "imap.example.com",
            "imap_port": 993,
            "imap_security": MailAccount.ImapSecurity.SSL,
            "username": "admin",
            "password": "wrong",
            "account_type": MailAccount.MailAccountType.IMAP,
            "is_token": False,
        }
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.content.decode(), "Unable to connect to server")

    @mock.patch(
        "paperless_mail.oauth.PaperlessMailOAuth2Manager.refresh_account_oauth_token",
    )
    def test_mail_account_test_view_refresh_token(
        self,
        mock_refresh_account_oauth_token,
    ):
        """
        GIVEN:
            - Mail account with expired token
        WHEN:
            - Mail account is tested
        THEN:
            - Should refresh the token
        """
        existing_account = MailAccount.objects.create(
            imap_server="imap.example.com",
            imap_port=993,
            imap_security=MailAccount.ImapSecurity.SSL,
            username="admin",
            password="secret",
            account_type=MailAccount.MailAccountType.GMAIL_OAUTH,
            refresh_token="oldtoken",
            expiration=timezone.now() - timedelta(days=1),
            is_token=True,
        )

        mock_refresh_account_oauth_token.return_value = True
        data = {
            "id": existing_account.id,
            "imap_server": "imap.example.com",
            "imap_port": 993,
            "imap_security": MailAccount.ImapSecurity.SSL,
            "username": "admin",
            "password": "****",
            "is_token": True,
        }
        self.client.post(self.url, data, format="json")
        self.assertEqual(mock_refresh_account_oauth_token.call_count, 1)

    @mock.patch(
        "paperless_mail.oauth.PaperlessMailOAuth2Manager.refresh_account_oauth_token",
    )
    def test_mail_account_test_view_refresh_token_fails(
        self,
        mock_mock_refresh_account_oauth_token,
    ):
        """
        GIVEN:
            - Mail account with expired token
        WHEN:
            - Mail account is tested
            - Token refresh fails
        THEN:
            - Should log an error
        """
        existing_account = MailAccount.objects.create(
            imap_server="imap.example.com",
            imap_port=993,
            imap_security=MailAccount.ImapSecurity.SSL,
            username="admin",
            password="secret",
            account_type=MailAccount.MailAccountType.GMAIL_OAUTH,
            refresh_token="oldtoken",
            expiration=timezone.now() - timedelta(days=1),
            is_token=True,
        )

        mock_mock_refresh_account_oauth_token.return_value = False
        data = {
            "id": existing_account.id,
            "imap_server": "imap.example.com",
            "imap_port": 993,
            "imap_security": MailAccount.ImapSecurity.SSL,
            "username": "admin",
            "password": "****",
            "is_token": True,
        }
        with self.assertLogs("paperless_mail", level="ERROR") as cm:
            response = self.client.post(self.url, data, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            error_str = cm.output[0]
            expected_str = "Unable to refresh oauth token"
            self.assertIn(expected_str, error_str)


class TestMailAccountProcess(APITestCase):
    def setUp(self):
        self.mailMocker = MailMocker()
        self.mailMocker.setUp()
        self.user = User.objects.create_superuser(
            username="testuser",
            password="testpassword",
        )
        self.client.force_authenticate(user=self.user)
        self.account = MailAccount.objects.create(
            imap_server="imap.example.com",
            imap_port=993,
            imap_security=MailAccount.ImapSecurity.SSL,
            username="admin",
            password="secret",
            account_type=MailAccount.MailAccountType.IMAP,
            owner=self.user,
        )
        self.url = f"/api/mail_accounts/{self.account.pk}/process/"

    @mock.patch("paperless_mail.tasks.process_mail_accounts.delay")
    def test_mail_account_process_view(self, m):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        m.assert_called_once()
