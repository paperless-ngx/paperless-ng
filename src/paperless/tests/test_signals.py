from unittest.mock import Mock

from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.test import TestCase
from django.test import override_settings

from paperless.signals import handle_failed_login
from paperless.signals import handle_social_account_updated


class TestFailedLoginLogging(TestCase):
    def setUp(self):
        super().setUp()

        self.creds = {
            "username": "john lennon",
        }

    def test_unauthenticated(self):
        """
        GIVEN:
            - Request with no authentication provided
        WHEN:
            - Request provided to signal handler
        THEN:
            - Unable to determine logged for unauthenticated user
        """
        request = HttpRequest()
        request.META = {}
        with self.assertLogs("paperless.auth") as logs:
            handle_failed_login(None, {}, request)
            self.assertEqual(
                logs.output,
                [
                    "INFO:paperless.auth:No authentication provided. Unable to determine IP address.",
                ],
            )

    def test_none(self):
        """
        GIVEN:
            - Request with no IP possible
        WHEN:
            - Request provided to signal handler
        THEN:
            - Unable to determine logged
        """
        request = HttpRequest()
        request.META = {}
        with self.assertLogs("paperless.auth") as logs:
            handle_failed_login(None, self.creds, request)

            self.assertEqual(
                logs.output,
                [
                    "INFO:paperless.auth:Login failed for user `john lennon`. Unable to determine IP address.",
                ],
            )

    def test_public(self):
        """
        GIVEN:
            - Request with publicly routeable IP
        WHEN:
            - Request provided to signal handler
        THEN:
            - Expected IP is logged
        """
        request = HttpRequest()
        request.META = {
            "HTTP_X_FORWARDED_FOR": "177.139.233.139",
        }
        with self.assertLogs("paperless.auth") as logs:
            handle_failed_login(None, self.creds, request)

            self.assertEqual(
                logs.output,
                [
                    "INFO:paperless.auth:Login failed for user `john lennon` from IP `177.139.233.139`.",
                ],
            )

    def test_private(self):
        """
        GIVEN:
            - Request with private range IP
        WHEN:
            - Request provided to signal handler
        THEN:
            - Expected IP is logged
            - IP is noted to be a private IP
        """
        request = HttpRequest()
        request.META = {
            "HTTP_X_FORWARDED_FOR": "10.0.0.1",
        }
        with self.assertLogs("paperless.auth") as logs:
            handle_failed_login(None, self.creds, request)

            self.assertEqual(
                logs.output,
                [
                    "INFO:paperless.auth:Login failed for user `john lennon` from private IP `10.0.0.1`.",
                ],
            )


class TestSyncSocialLoginGroups(TestCase):
    @override_settings(SOCIAL_ACCOUNT_SYNC_GROUPS=True)
    def test_sync_enabled(self):
        """
        GIVEN:
            - Enabled group syncing, a user, and a social login
        WHEN:
            - The social login is updated via signal after login
        THEN:
            - The user's groups are updated to match the social login's groups
        """
        group = Group.objects.create(name="group1")
        user = User.objects.create_user(username="testuser")
        sociallogin = Mock(
            user=user,
            account=Mock(
                extra_data={
                    "groups": ["group1"],
                },
            ),
        )
        handle_social_account_updated(
            sender=None,
            request=HttpRequest(),
            sociallogin=sociallogin,
        )
        self.assertEqual(list(user.groups.all()), [group])

    @override_settings(SOCIAL_ACCOUNT_SYNC_GROUPS=False)
    def test_sync_disabled(self):
        """
        GIVEN:
            - Disabled group syncing, a user, and a social login
        WHEN:
            - The social login is updated via signal after login
        THEN:
            - The user's groups are not updated
        """
        Group.objects.create(name="group1")
        user = User.objects.create_user(username="testuser")
        sociallogin = Mock(
            user=user,
            account=Mock(
                extra_data={
                    "groups": ["group1"],
                },
            ),
        )
        handle_social_account_updated(
            sender=None,
            request=HttpRequest(),
            sociallogin=sociallogin,
        )
        self.assertEqual(list(user.groups.all()), [])

    @override_settings(SOCIAL_ACCOUNT_SYNC_GROUPS=True)
    def test_no_groups(self):
        """
        GIVEN:
            - Enabled group syncing, a user, and a social login with no groups
        WHEN:
            - The social login is updated via signal after login
        THEN:
            - The user's groups are cleared to match the social login's groups
        """
        group = Group.objects.create(name="group1")
        user = User.objects.create_user(username="testuser")
        user.groups.add(group)
        user.save()
        sociallogin = Mock(
            user=user,
            account=Mock(
                extra_data={
                    "groups": [],
                },
            ),
        )
        handle_social_account_updated(
            sender=None,
            request=HttpRequest(),
            sociallogin=sociallogin,
        )
        self.assertEqual(list(user.groups.all()), [])
