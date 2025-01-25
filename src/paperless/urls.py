import os

from allauth.account import views as allauth_account_views
from allauth.mfa.base import views as allauth_mfa_views
from allauth.socialaccount import views as allauth_social_account_views
from allauth.urls import build_provider_urlpatterns
from django.conf import settings
from django.conf.urls import include
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path
from django.urls import re_path
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import RedirectView
from django.views.static import serve
from rest_framework.authtoken import views
from rest_framework.routers import DefaultRouter

from documents.views import ArchiveSerialNumberPrefixViewSet
from documents.views import BulkDownloadView
from documents.views import BulkEditObjectsView
from documents.views import BulkEditView
from documents.views import CorrespondentViewSet
from documents.views import CustomFieldViewSet
from documents.views import DocumentTypeViewSet
from documents.views import GlobalSearchView
from documents.views import IndexView
from documents.views import LogViewSet
from documents.views import PostDocumentView
from documents.views import RemoteVersionView
from documents.views import SavedViewViewSet
from documents.views import SearchAutoCompleteView
from documents.views import SelectionDataView
from documents.views import SharedLinkView
from documents.views import ShareLinkViewSet
from documents.views import StatisticsView
from documents.views import StoragePathViewSet
from documents.views import SystemStatusView
from documents.views import TagViewSet
from documents.views import TasksViewSet
from documents.views import TrashView
from documents.views import UiSettingsView
from documents.views import UnifiedSearchViewSet
from documents.views import WorkflowActionViewSet
from documents.views import WorkflowTriggerViewSet
from documents.views import WorkflowViewSet
from paperless.consumers import StatusConsumer
from paperless.views import ApplicationConfigurationViewSet
from paperless.views import DisconnectSocialAccountView
from paperless.views import FaviconView
from paperless.views import GenerateAuthTokenView
from paperless.views import GroupViewSet
from paperless.views import ProfileView
from paperless.views import SocialAccountProvidersView
from paperless.views import TOTPView
from paperless.views import UserViewSet
from paperless_mail.views import MailAccountViewSet
from paperless_mail.views import MailRuleViewSet
from paperless_mail.views import OauthCallbackView

api_router = DefaultRouter()
api_router.register(r"asn_prefix", ArchiveSerialNumberPrefixViewSet)
api_router.register(r"correspondents", CorrespondentViewSet)
api_router.register(r"document_types", DocumentTypeViewSet)
api_router.register(r"documents", UnifiedSearchViewSet)
api_router.register(r"logs", LogViewSet, basename="logs")
api_router.register(r"tags", TagViewSet)
api_router.register(r"saved_views", SavedViewViewSet)
api_router.register(r"storage_paths", StoragePathViewSet)
api_router.register(r"tasks", TasksViewSet, basename="tasks")
api_router.register(r"users", UserViewSet, basename="users")
api_router.register(r"groups", GroupViewSet, basename="groups")
api_router.register(r"mail_accounts", MailAccountViewSet)
api_router.register(r"mail_rules", MailRuleViewSet)
api_router.register(r"share_links", ShareLinkViewSet)
api_router.register(r"workflow_triggers", WorkflowTriggerViewSet)
api_router.register(r"workflow_actions", WorkflowActionViewSet)
api_router.register(r"workflows", WorkflowViewSet)
api_router.register(r"custom_fields", CustomFieldViewSet)
api_router.register(r"config", ApplicationConfigurationViewSet)


urlpatterns = [
    re_path(
        r"^api/",
        include(
            [
                re_path(
                    "^auth/",
                    include(
                        ("rest_framework.urls", "rest_framework"),
                        namespace="rest_framework",
                    ),
                ),
                re_path(
                    "^search/",
                    include(
                        [
                            re_path(
                                "^$",
                                GlobalSearchView.as_view(),
                                name="global_search",
                            ),
                            re_path(
                                "^autocomplete/",
                                SearchAutoCompleteView.as_view(),
                                name="autocomplete",
                            ),
                        ],
                    ),
                ),
                re_path(
                    "^statistics/",
                    StatisticsView.as_view(),
                    name="statistics",
                ),
                re_path(
                    "^documents/",
                    include(
                        [
                            re_path(
                                "^post_document/",
                                PostDocumentView.as_view(),
                                name="post_document",
                            ),
                            re_path(
                                "^bulk_edit/",
                                BulkEditView.as_view(),
                                name="bulk_edit",
                            ),
                            re_path(
                                "^bulk_download/",
                                BulkDownloadView.as_view(),
                                name="bulk_download",
                            ),
                            re_path(
                                "^selection_data/",
                                SelectionDataView.as_view(),
                                name="selection_data",
                            ),
                        ],
                    ),
                ),
                re_path(
                    "^bulk_edit_objects/",
                    BulkEditObjectsView.as_view(),
                    name="bulk_edit_objects",
                ),
                re_path(
                    "^remote_version/",
                    RemoteVersionView.as_view(),
                    name="remoteversion",
                ),
                re_path(
                    "^ui_settings/",
                    UiSettingsView.as_view(),
                    name="ui_settings",
                ),
                path(
                    "token/",
                    views.obtain_auth_token,
                ),
                re_path(
                    "^profile/",
                    include(
                        [
                            re_path(
                                "^$",
                                ProfileView.as_view(),
                                name="profile_view",
                            ),
                            path(
                                "generate_auth_token/",
                                GenerateAuthTokenView.as_view(),
                            ),
                            path(
                                "disconnect_social_account/",
                                DisconnectSocialAccountView.as_view(),
                            ),
                            path(
                                "social_account_providers/",
                                SocialAccountProvidersView.as_view(),
                            ),
                            path(
                                "totp/",
                                TOTPView.as_view(),
                                name="totp_view",
                            ),
                        ],
                    ),
                ),
                re_path(
                    "^status/",
                    SystemStatusView.as_view(),
                    name="system_status",
                ),
                re_path(
                    "^trash/",
                    TrashView.as_view(),
                    name="trash",
                ),
                re_path(
                    r"^oauth/callback/",
                    OauthCallbackView.as_view(),
                    name="oauth_callback",
                ),
                *api_router.urls,
            ],
        ),
    ),
    re_path(r"share/(?P<slug>\w+)/?$", SharedLinkView.as_view()),
    re_path(r"^favicon.ico$", FaviconView.as_view(), name="favicon"),
    re_path(r"admin/", admin.site.urls),
    re_path(
        r"^fetch/",
        include(
            [
                re_path(
                    r"^doc/(?P<pk>\d+)$",
                    RedirectView.as_view(
                        url=settings.BASE_URL + "api/documents/%(pk)s/download/",
                    ),
                ),
                re_path(
                    r"^thumb/(?P<pk>\d+)$",
                    RedirectView.as_view(
                        url=settings.BASE_URL + "api/documents/%(pk)s/thumb/",
                    ),
                ),
                re_path(
                    r"^preview/(?P<pk>\d+)$",
                    RedirectView.as_view(
                        url=settings.BASE_URL + "api/documents/%(pk)s/preview/",
                    ),
                ),
            ],
        ),
    ),
    # Frontend assets TODO: this is pretty bad, but it works.
    path(
        "assets/<path:path>",
        RedirectView.as_view(
            url=settings.STATIC_URL + "frontend/en-US/assets/%(path)s",
        ),
        # TODO: with localization, this is even worse! :/
    ),
    # App logo
    re_path(
        r"^logo(?P<path>.*)$",
        serve,
        kwargs={"document_root": os.path.join(settings.MEDIA_ROOT, "logo")},
    ),
    # allauth
    path(
        "accounts/",
        include(
            [
                # see allauth/account/urls.py
                # login, logout, signup
                path("login/", allauth_account_views.login, name="account_login"),
                path("logout/", allauth_account_views.logout, name="account_logout"),
                path("signup/", allauth_account_views.signup, name="account_signup"),
                # password reset
                path(
                    "password/",
                    include(
                        [
                            path(
                                "reset/",
                                allauth_account_views.password_reset,
                                name="account_reset_password",
                            ),
                            path(
                                "reset/done/",
                                allauth_account_views.password_reset_done,
                                name="account_reset_password_done",
                            ),
                            path(
                                "reset/key/done/",
                                allauth_account_views.password_reset_from_key_done,
                                name="account_reset_password_from_key_done",
                            ),
                        ],
                    ),
                ),
                re_path(
                    r"^password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$",
                    allauth_account_views.password_reset_from_key,
                    name="account_reset_password_from_key",
                ),
                # social account base urls, see allauth/socialaccount/urls.py
                path(
                    "3rdparty/",
                    include(
                        [
                            path(
                                "login/cancelled/",
                                allauth_social_account_views.login_cancelled,
                                name="socialaccount_login_cancelled",
                            ),
                            path(
                                "login/error/",
                                allauth_social_account_views.login_error,
                                name="socialaccount_login_error",
                            ),
                            path(
                                "signup/",
                                allauth_social_account_views.signup,
                                name="socialaccount_signup",
                            ),
                        ],
                    ),
                ),
                *build_provider_urlpatterns(),
                # mfa, see allauth/mfa/base/urls.py
                path(
                    "2fa/authenticate/",
                    allauth_mfa_views.authenticate,
                    name="mfa_authenticate",
                ),
            ],
        ),
    ),
    # Root of the Frontend
    re_path(
        r".*",
        login_required(ensure_csrf_cookie(IndexView.as_view())),
        name="base",
    ),
]


websocket_urlpatterns = [
    path(settings.BASE_URL.lstrip("/") + "ws/status/", StatusConsumer.as_asgi()),
]

# Text in each page's <h1> (and above login form).
admin.site.site_header = "Paperless-ngx"
# Text at the end of each page's <title>.
admin.site.site_title = "Paperless-ngx"
# Text at the top of the admin index page.
admin.site.index_title = _("Paperless-ngx administration")
