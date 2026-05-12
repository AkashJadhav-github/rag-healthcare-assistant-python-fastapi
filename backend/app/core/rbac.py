from enum import Enum
from typing import Set

from fastapi import HTTPException, status

from ..models.user import UserRole


class Permission(str, Enum):
    QUERY = "query"
    INGEST = "ingest"
    VIEW_HISTORY = "view_history"
    VIEW_ALL_HISTORY = "view_all_history"
    REINDEX = "reindex"
    MANAGE_USERS = "manage_users"
    VIEW_AUDIT = "view_audit"
    DELETE_DOCUMENTS = "delete_documents"
    ADMIN = "admin"


ROLE_PERMISSIONS: dict[UserRole, Set[Permission]] = {
    UserRole.VIEWER: {
        Permission.QUERY,
        Permission.VIEW_HISTORY,
    },
    UserRole.CLINICIAN: {
        Permission.QUERY,
        Permission.VIEW_HISTORY,
        Permission.INGEST,
    },
    UserRole.RESEARCHER: {
        Permission.QUERY,
        Permission.VIEW_HISTORY,
        Permission.INGEST,
        Permission.VIEW_ALL_HISTORY,
    },
    UserRole.ADMIN: {
        Permission.QUERY,
        Permission.INGEST,
        Permission.VIEW_HISTORY,
        Permission.VIEW_ALL_HISTORY,
        Permission.REINDEX,
        Permission.MANAGE_USERS,
        Permission.VIEW_AUDIT,
        Permission.DELETE_DOCUMENTS,
        Permission.ADMIN,
    },
}


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def require_permission(permission: Permission):
    """Dependency factory for endpoint-level permission checks."""

    def check(current_user) -> None:
        if not has_permission(current_user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value} requires higher role",
            )

    return check
