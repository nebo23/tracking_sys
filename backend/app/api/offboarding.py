"""The offboarding export routes of a closing agency (specification 017-B, D-098 D2 to D5).

Browser sessions only: a read or ingest key is refused by BrowserDep. The caller is resolved as
for the closure routes: an active Owner of an active or closing agency. A request needs a
closing agency, the window before 24 hours ahead of the closing time and the reauthentication
of account closure; it is throttled like the closure request, replaces the open export and is
audited. The worker builds the file; the download streams its sealed parts in order with
Content-Length and Cache-Control: no-store. Answers carry identifiers, codes, counts, digests and
times only.
"""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.auth import throttle
from app.api.dependencies import BrowserDep, SessionDep
from app.api.schemas import AgencyExportInput, AgencyExportState, AgencyExportView
from app.services.agency_exports import (
    FILENAME,
    AgencyExportService,
    open_stream,
    window_end,
)
from app.services.agency_offboarding import export_view_status

router = APIRouter(tags=["Plans and closure"])
ZIP_DOWNLOAD = {
    200: {
        "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        "description": "The offboarding ZIP, streamed part by part.",
    }
}


def _service(request: Request, session, browser) -> AgencyExportService:
    return AgencyExportService(session, browser.user.id, request.app.state.settings)


def _state(service: AgencyExportService, agency_id: UUID) -> AgencyExportState:
    agency, closure, item, clock = service.read(agency_id)
    view = None
    if item is not None:
        view = AgencyExportView.model_validate(item).model_copy(
            update={"status": export_view_status(item, clock)}
        )
    return AgencyExportState(
        agency_id=agency.id,
        window_ends_at=window_end(closure) if agency.status == "closing" else None,
        export=view,
    )


# Request the offboarding export (Owner of a closing agency, reauthenticated, until 24 hours
# before the closing time). The open export is replaced; the worker builds the new file.
@router.post(
    "/agencies/{agency_id}/closure/export", status_code=202, response_model=AgencyExportState
)
def request_export(
    agency_id: UUID,
    data: AgencyExportInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> AgencyExportState:
    throttle(request, "agency-export", str(browser.user.id))
    service = _service(request, session, browser)
    service.request(
        agency_id,
        password=data.password.get_secret_value() if data.password is not None else None,
        user=browser.user,
        auth_session=browser.session,
    )
    return _state(service, agency_id)


# The latest offboarding export and the request window, for Owners while active or closing.
@router.get("/agencies/{agency_id}/closure/export", response_model=AgencyExportState)
def read_export(
    agency_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> AgencyExportState:
    return _state(_service(request, session, browser), agency_id)


# Download the ready offboarding export of a closing agency (Owners only). The scope is
# resolved again and the download counted before the parts stream.
@router.get("/agencies/{agency_id}/closure/export/download", responses=ZIP_DOWNLOAD)
def download_export(
    agency_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> StreamingResponse:
    settings = request.app.state.settings
    item = _service(request, session, browser).open_download(agency_id)
    keyring = settings.token_keys()
    assert keyring is not None
    stream = open_stream(request.app.state.engine, keyring, item)
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{FILENAME}"',
            "Content-Length": str(item.byte_size),
            "Cache-Control": "no-store",
        },
    )
