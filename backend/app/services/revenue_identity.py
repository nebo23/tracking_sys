"""Sale-to-person association (specification 007-C, D-075 decision J10).

Phase P4 implements trusted association assertions, revisions and financial unlinking. Until
then no person holds a verified association, so financial customer qualification is false.
"""

from uuid import UUID

from sqlalchemy.orm import Session


def has_verified_purchase(session: Session, client_id: UUID, group: list[UUID]) -> bool:
    """Whether any person of the group has a currently associated verified capture."""
    return False
