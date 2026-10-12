"""Unit tests for the role -> permission matrix (pure logic, no HTTP or DB).

The expected table is copied from docs/rbac-authorization-matrix.md, so a change to
ROLE_PERMISSIONS that is not mirrored in the doc fails here.
"""

import itertools

import pytest

from app.auth.permissions import ROLE_PERMISSIONS, Permission, role_allows
from app.models.enums import ProjectRole

EXPECTED_GRANTS = {
    (ProjectRole.admin, Permission.project_create),
    (ProjectRole.admin, Permission.user_manage),
    (ProjectRole.admin, Permission.task_assign),
    (ProjectRole.manager, Permission.task_assign),
    (ProjectRole.owner, Permission.task_assign),
}

ALL_PAIRS = list(itertools.product(ProjectRole, Permission))
DENIED = [pair for pair in ALL_PAIRS if pair not in EXPECTED_GRANTS]


@pytest.mark.parametrize(("role", "permission"), sorted(EXPECTED_GRANTS))
def test_granted_permissions(role: ProjectRole, permission: Permission) -> None:
    assert role_allows(role, permission)


@pytest.mark.parametrize(("role", "permission"), DENIED)
def test_everything_else_is_denied(role: ProjectRole, permission: Permission) -> None:
    assert not role_allows(role, permission)


def test_every_role_has_an_entry() -> None:
    """A new ProjectRole without a matrix entry would raise KeyError at request time."""
    assert set(ROLE_PERMISSIONS) == set(ProjectRole)


def test_member_has_no_role_based_permissions() -> None:
    """Members act on their own tasks through the assignee check, not through a role."""
    assert ROLE_PERMISSIONS[ProjectRole.member] == set()
