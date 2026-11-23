"""Persisted 006/007 inputs for the in-memory 008-A engine (specification 007-C, D-075 J12).

This adapter reads the actual persisted identity journey and the actual persisted sale
associations and ledger state of one person, and turns them into the 008-A contracts
(Touchpoint, Conversion, SaleState). It verifies the identity and financial handoff; it does
not run, store or schedule attribution, which remains the successor work of specification 008
(production persistence is not part of D-075).

- Touchpoints are the person's assigned page views, link clicks and form submissions (the
  two-time rule of 006; marked events never appear), with their collection subject's current
  attribution consent. A managed link or a retained utm_campaign value makes a campaign
  interaction; anything else is a direct visit.
- A conversion exists for every currently qualifying association (owned segment, current
  identity_link and attribution consent, verified sale in the published ledger). Its ID binds
  the association to the person's visible root, so an ownership change (merge, unmerge or
  erasure) yields a new conversion identity instead of mutating an old one.
- The sale state is the published transaction projection, so refunds and releases change the
  revenue the engine allocates without changing any amount.
"""

from datetime import datetime
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attribution import (
    Association,
    Conversion,
    ConversionKind,
    EvidenceClass,
    SaleState,
    Touchpoint,
)
from app.ledger import Currency, LedgerScope
from app.models import CollectionSubject, LedgerTransaction, LinkCampaign, ManagedLink
from app.privacy.consent import Purpose
from app.services.collection import consent_view
from app.services.identity import journey_events, person_group, root_of

TOUCH_TYPES = frozenset({"page_view", "link_click", "form_submit"})


def touchpoints(
    session: Session, agency_id: UUID, client_id: UUID, person_id: UUID, now: datetime
) -> list[Touchpoint]:
    root = root_of(session, person_id)
    consents: dict[UUID, object] = {}
    result = []
    for event, _link in journey_events(session, client_id, person_id, now):
        if event.event_type not in TOUCH_TYPES:
            continue
        if event.subject_id not in consents:
            subject = session.get(CollectionSubject, event.subject_id)
            consents[event.subject_id] = consent_view(session, subject, now).states[
                Purpose.ATTRIBUTION
            ]
        campaign = None
        link_ref = None
        if event.link_id is not None:
            link_ref = str(event.link_id)
            campaign = session.scalar(
                select(LinkCampaign.public_code)
                .join(ManagedLink, ManagedLink.campaign_id == LinkCampaign.id)
                .where(ManagedLink.id == event.link_id)
            )
        url = (event.payload or {}).get("url")
        if campaign is None and isinstance(url, str):
            campaign = dict(parse_qsl(urlsplit(url).query)).get("utm_campaign")
        tagged = campaign is not None or link_ref is not None
        result.append(
            Touchpoint(
                str(event.event_id),
                agency_id,
                client_id,
                str(root),
                EvidenceClass.CAMPAIGN_INTERACTION if tagged else EvidenceClass.DIRECT_VISIT,
                event.occurred_at,
                Association.ASSIGNED,
                consents[event.subject_id],
                source="tracker" if event.trust_rank == 1 else "trusted_sender",
                campaign_ref=campaign,
                link_ref=link_ref,
            )
        )
    return result


def sale_conversions(
    session: Session, agency_id: UUID, client_id: UUID, person_id: UUID, now: datetime
) -> list[tuple[Conversion, SaleState]]:
    from app.services.ledger_store import require_current
    from app.services.revenue import load_rows
    from app.services.revenue_identity import _qualifying

    root = root_of(session, person_id)
    group = person_group(session, client_id, person_id)
    state = require_current(session, agency_id, client_id, load_rows(session, agency_id, client_id))
    found = []
    for row in _qualifying(session, agency_id, client_id, group, now):
        transaction = session.scalar(
            select(LedgerTransaction).where(
                LedgerTransaction.client_id == client_id,
                LedgerTransaction.generation == state.generation,
                LedgerTransaction.source_account_id == row.source_account_id,
                LedgerTransaction.operation_id == row.sale_operation_id,
            )
        )
        scope = LedgerScope(agency_id, client_id, row.source_account_id)
        sale = SaleState(
            scope,
            row.sale_operation_id,
            Currency(transaction.currency, transaction.currency_exponent),
            transaction.sale_effective_at,
            max(transaction.net, 0),
        )
        conversion = Conversion(
            f"{row.association_id}:{root}",
            agency_id,
            client_id,
            str(root),
            ConversionKind.SALE,
            transaction.sale_effective_at,
            row.source_account_id,
            row.sale_operation_id,
        )
        found.append((conversion, sale))
    return found
