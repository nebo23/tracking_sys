"""Deterministic matching of one assertion's keys within one client (design section 4.2, R1-R5).

decide() is pure: the service resolves every asserted key's current state under the client
lock (new, owned with its original owner, visible root and merge dependency, or contested with
its candidates) and applies the returned decision. Two automatic rules are deliberately absent:
the engine never merges two existing persons, and keys never join across assertions.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

Outcome = Literal["linked", "ambiguous", "contested_identifier"]


@dataclass(frozen=True)
class AssertedKey:
    index: int
    kind: str
    state: Literal["new", "owned", "contested"]
    owner: UUID | None = None  # original owner of an owned key
    root: UUID | None = None  # visible root of that owner
    owners: frozenset[UUID] = frozenset()  # original owners the key's evidence names
    merge_id: UUID | None = None  # merge dependency recorded on the key
    candidates: frozenset[UUID] = frozenset()  # candidates of a contested key


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    # The existing person the link and new keys belong to; None with create_new or ambiguity.
    person: UUID | None = None
    create_new: bool = False
    contest: tuple[int, ...] = ()  # indexes of owned keys that become contested
    candidates: tuple[UUID, ...] = ()  # ambiguous candidates
    original_owners: frozenset[UUID] = field(default_factory=frozenset)
    merge_id: UUID | None = None
    rule: str = ""


def decide(
    keys: Sequence[AssertedKey],
    *,
    root_holds_reference: dict[UUID, bool],
    edge_of: dict[UUID, UUID],
) -> Decision:
    """Apply R5, then R3, R2-P, R4 and R2 over the eligible keys.

    root_holds_reference says whether any person of a visible root's merge group owns a
    customer_ref; edge_of maps a merged root to its active merge edge.
    """
    eligible = [key for key in keys if key.state != "contested"]
    contested = [key for key in keys if key.state == "contested"]
    owned = [key for key in eligible if key.state == "owned"]
    new = [key for key in eligible if key.state == "new"]
    if not eligible:
        candidates = sorted({person for key in contested for person in key.candidates}, key=str)
        return Decision("ambiguous", candidates=tuple(candidates), rule="R5")
    if not owned:
        return Decision("linked", create_new=True, rule="R1")
    roots = {key.root for key in owned}
    reference = next((key for key in eligible if key.kind == "customer_ref"), None)
    if reference is not None:
        if reference.state == "owned":
            others = [key for key in owned if key.root != reference.root]
            if others:
                return _owned(
                    reference.root,
                    [key for key in owned if key.root == reference.root],
                    edge_of,
                    outcome="contested_identifier",
                    contest=tuple(key.index for key in others),
                    rule="R3a",
                )
        else:
            if any(root_holds_reference.get(root, False) for root in roots):
                return Decision(
                    "contested_identifier",
                    create_new=True,
                    contest=tuple(key.index for key in owned),
                    rule="R3b",
                )
            if len(roots) > 1:
                return _ambiguous(owned, "R4")
    if all(key.kind == "phone" for key in owned) and any(
        key.kind in {"email", "customer_ref"} for key in new
    ):
        return Decision(
            "contested_identifier",
            create_new=True,
            contest=tuple(key.index for key in owned),
            rule="R2P",
        )
    if len(roots) > 1:
        return _ambiguous(owned, "R4")
    (root,) = roots
    return _owned(root, owned, edge_of, outcome="linked", contest=(), rule="R2")


def _ambiguous(owned: Sequence[AssertedKey], rule: str) -> Decision:
    candidates = sorted({person for key in owned for person in key.owners}, key=str)
    return Decision("ambiguous", candidates=tuple(candidates), rule=rule)


def _owned(
    root: UUID | None,
    anchors: Sequence[AssertedKey],
    edge_of: dict[UUID, UUID],
    *,
    outcome: Outcome,
    contest: tuple[int, ...],
    rule: str,
) -> Decision:
    owners = frozenset(person for key in anchors for person in key.owners)
    inherited = {key.merge_id for key in anchors if key.merge_id is not None}
    merge_id = next(iter(inherited)) if inherited else None
    if len(owners) > 1 and merge_id is None and root is not None:
        merge_id = edge_of.get(root)
    if merge_id is not None or len(owners) > 1:
        person = root
    else:
        (person,) = owners
    return Decision(
        outcome,
        person=person,
        contest=contest,
        original_owners=owners,
        merge_id=merge_id,
        rule=rule,
    )
