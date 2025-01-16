from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from guardian.core import ObjectPermissionChecker
from guardian.models import GroupObjectPermission
from guardian.shortcuts import assign_perm
from guardian.shortcuts import get_objects_for_user
from guardian.shortcuts import get_users_with_perms
from guardian.shortcuts import remove_perm
from rest_framework.permissions import BasePermission
from rest_framework.permissions import DjangoObjectPermissions


class PaperlessObjectPermissions(DjangoObjectPermissions):
    """
    A permissions backend that checks for object-level permissions
    or for ownership.
    """

    perms_map = {
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
        "POST": ["%(app_label)s.add_%(model_name)s"],
        "PUT": ["%(app_label)s.change_%(model_name)s"],
        "PATCH": ["%(app_label)s.change_%(model_name)s"],
        "DELETE": ["%(app_label)s.delete_%(model_name)s"],
    }

    def has_object_permission(self, request, view, obj):
        if hasattr(obj, "owner") and obj.owner is not None:
            if request.user == obj.owner:
                return True
            else:
                return super().has_object_permission(request, view, obj)
        else:
            return True  # no owner


class PaperlessAdminPermissions(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_staff


def get_groups_with_only_permission(obj, codename):
    ctype = ContentType.objects.get_for_model(obj)
    permission = Permission.objects.get(content_type=ctype, codename=codename)
    group_object_perm_group_ids = (
        GroupObjectPermission.objects.filter(
            object_pk=obj.pk,
            content_type=ctype,
        )
        .filter(permission=permission)
        .values_list("group_id")
    )
    return Group.objects.filter(id__in=group_object_perm_group_ids).distinct()


def set_permissions_for_object(permissions: list[str], object, *, merge: bool = False):
    """
    Set permissions for an object. The permissions are given as a list of strings
    in the format "action_modelname", e.g. "view_document".

    If merge is True, the permissions are merged with the existing permissions and
    no users or groups are removed. If False, the permissions are set to exactly
    the given list of users and groups.
    """

    for action in permissions:
        permission = f"{action}_{object.__class__.__name__.lower()}"
        # users
        users_to_add = User.objects.filter(id__in=permissions[action]["users"])
        users_to_remove = (
            get_users_with_perms(
                object,
                only_with_perms_in=[permission],
                with_group_users=False,
            )
            if not merge
            else User.objects.none()
        )
        if len(users_to_add) > 0 and len(users_to_remove) > 0:
            users_to_remove = users_to_remove.exclude(id__in=users_to_add)
        if len(users_to_remove) > 0:
            for user in users_to_remove:
                remove_perm(permission, user, object)
        if len(users_to_add) > 0:
            for user in users_to_add:
                assign_perm(permission, user, object)
                if action == "change":
                    # change gives view too
                    assign_perm(
                        f"view_{object.__class__.__name__.lower()}",
                        user,
                        object,
                    )
        # groups
        groups_to_add = Group.objects.filter(id__in=permissions[action]["groups"])
        groups_to_remove = (
            get_groups_with_only_permission(
                object,
                permission,
            )
            if not merge
            else Group.objects.none()
        )
        if len(groups_to_add) > 0 and len(groups_to_remove) > 0:
            groups_to_remove = groups_to_remove.exclude(id__in=groups_to_add)
        if len(groups_to_remove) > 0:
            for group in groups_to_remove:
                remove_perm(permission, group, object)
        if len(groups_to_add) > 0:
            for group in groups_to_add:
                assign_perm(permission, group, object)
                if action == "change":
                    # change gives view too
                    assign_perm(
                        f"view_{object.__class__.__name__.lower()}",
                        group,
                        object,
                    )


def get_objects_for_user_owner_aware(user, perms, Model) -> QuerySet:
    objects_owned = Model.objects.filter(owner=user)
    objects_unowned = Model.objects.filter(owner__isnull=True)
    objects_with_perms = get_objects_for_user(
        user=user,
        perms=perms,
        klass=Model,
        accept_global_perms=False,
    )
    return objects_owned | objects_unowned | objects_with_perms


def has_perms_owner_aware(user, perms, obj):
    checker = ObjectPermissionChecker(user)
    return obj.owner is None or obj.owner == user or checker.has_perm(perms, obj)


class PaperlessNotePermissions(BasePermission):
    """
    Permissions class that checks for model permissions for Notes.
    """

    perms_map = {
        "OPTIONS": ["documents.view_note"],
        "GET": ["documents.view_note"],
        "POST": ["documents.add_note"],
        "DELETE": ["documents.delete_note"],
    }

    def has_permission(self, request, view):
        if not request.user or (not request.user.is_authenticated):  # pragma: no cover
            return False

        perms = self.perms_map[request.method]

        return request.user.has_perms(perms)
