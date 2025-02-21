import logging

from django.conf import settings
from python_ipware import IpWare

logger = logging.getLogger("paperless.auth")


# https://docs.djangoproject.com/en/4.1/ref/contrib/auth/#django.contrib.auth.signals.user_login_failed
def handle_failed_login(sender, credentials, request, **kwargs):
    ipware = IpWare(proxy_list=settings.TRUSTED_PROXIES)
    client_ip, _ = ipware.get_client_ip(
        meta=request.META,
    )
    username = credentials.get("username")
    log_output = (
        "No authentication provided"
        if username is None
        else f"Login failed for user `{username}`"
    )

    if client_ip is None:
        log_output += ". Unable to determine IP address."
    else:
        if client_ip.is_global:
            # We got the client's IP address
            log_output += f" from IP `{client_ip}`."
        else:
            # The client's IP address is private
            log_output += f" from private IP `{client_ip}`."

    logger.info(log_output)


def handle_social_account_updated(sender, request, sociallogin, **kwargs):
    """
    Handle the social account update signal.
    """
    from django.contrib.auth.models import Group

    social_account_groups = sociallogin.account.extra_data.get(
        "groups",
        [],
    )  # None if not found
    if settings.SOCIAL_ACCOUNT_SYNC_GROUPS and social_account_groups is not None:
        groups = Group.objects.filter(name__in=social_account_groups)
        logger.debug(
            f"Syncing groups for user `{sociallogin.user}`: {social_account_groups}",
        )
        sociallogin.user.groups.set(groups, clear=True)
