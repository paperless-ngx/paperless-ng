import abc
from email import message_from_bytes
from email import policy
from email.message import Message
from pathlib import Path

from django.conf import settings
from gnupg import GPG
from imap_tools import MailMessage

from documents.loggers import LoggingMixin


class MailMessagePreprocessor(abc.ABC):
    """
    Defines the interface for preprocessors that alter messages before they are handled in MailAccountHandler
    """

    NAME: str = "MailMessagePreprocessor"

    @staticmethod
    @abc.abstractmethod
    def able_to_run() -> bool:
        """
        Return True if the conditions are met for the preprocessor to run, False otherwise

        If False, run(message) will not be called
        """

    @abc.abstractmethod
    def run(self, message: MailMessage) -> MailMessage:
        """
        Performs the actual preprocessing task
        """


class MailMessageDecryptor(MailMessagePreprocessor, LoggingMixin):
    logging_name = "paperless_mail_message_decryptor"

    NAME = "MailMessageDecryptor"

    def __init__(self):
        super().__init__()
        self.renew_logging_group()
        self._gpg = GPG(gnupghome=settings.EMAIL_GNUPG_HOME)

    @staticmethod
    def able_to_run() -> bool:
        if not settings.EMAIL_ENABLE_GPG_DECRYPTOR:
            return False
        if settings.EMAIL_GNUPG_HOME is None:
            return True
        return Path(settings.EMAIL_GNUPG_HOME).is_dir()

    def run(self, message: MailMessage) -> MailMessage:
        if not hasattr(message, "obj"):
            self.log.debug("Message does not have 'obj' attribute")
            return message
        if message.obj.get_content_type() != "multipart/encrypted":
            self.log.debug("Message not encrypted. Keep unchanged")
            return message

        self.log.debug("Message is encrypted.")
        email_message = self._to_email_message(message)
        decrypted_raw_message = self._gpg.decrypt(email_message.as_string())

        if not decrypted_raw_message.ok:
            self.log.debug(
                f"Message decryption failed with status message "
                f"{decrypted_raw_message.status}",
            )
            raise Exception(
                f"Decryption failed: {decrypted_raw_message.status}, {decrypted_raw_message.stderr}",
            )
        self.log.debug("Message decrypted successfully.")

        decrypted_message = self._build_decrypted_message(
            decrypted_raw_message,
            email_message,
        )

        return MailMessage(
            [(f"UID {message.uid}".encode(), decrypted_message.as_bytes())],
        )

    @staticmethod
    def _to_email_message(message: MailMessage) -> Message:
        email_message = message_from_bytes(
            message.obj.as_bytes(),
            policy=policy.default,
        )
        return email_message

    @staticmethod
    def _build_decrypted_message(decrypted_raw_message, email_message):
        decrypted_message = message_from_bytes(
            decrypted_raw_message.data,
            policy=policy.default,
        )
        for header, value in email_message.items():
            if not decrypted_message.get(header):
                decrypted_message.add_header(header, value)
        return decrypted_message
