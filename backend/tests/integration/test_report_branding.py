"""016-C agency branding on disposable PostgreSQL (D-095 D11, RV17, RV19).

The profile and logo routes, their permissions, safe logo headers and audit; the display name
in report emails; and the isolation of agencies' exports, schedules and branding. PNG files are
generated in memory; no image is decoded.
"""

# ruff: noqa: F811

import zlib
from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_report_delivery_contract import png
from test_report_exports import bodies, created, download, exports_url, fixed_clock  # noqa: F401
from test_report_schedules import due, schedule_body, scheduled, schedules_url, worker

from app.models import AuditEvent
from app.services.mail import process_mail

pytestmark = pytest.mark.integration


def branding_url(agency) -> str:
    return f"/agencies/{agency}/branding"


def put_logo(reader, agency, data, media="image/png"):
    return reader.put(f"{branding_url(agency)}/logo", content=data, headers={"Content-Type": media})


def audited(w) -> int:
    with Session(w.db.migration) as session:
        return len(
            session.scalars(
                select(AuditEvent.id).where(AuditEvent.action == "branding.updated")
            ).all()
        )


def test_rv17_profile(authenticated_world):
    w = authenticated_world
    owner, admin, analyst, viewer = (
        w.signed_in(name) for name in ("owner_a", "admin", "analyst", "viewer")
    )
    empty = viewer.get(branding_url(w.a))
    assert empty.status_code == 200
    assert empty.json() == {
        "agency_id": str(w.a),
        "configured": False,
        "display_name": None,
        "accent_color": None,
        "logo": None,
        "updated_at": None,
    }
    body = {"display_name": "Synthetic Studio", "accent_color": "#1a2b3c"}
    for reader in (analyst, viewer):
        assert reader.put(branding_url(w.a), json=body).status_code == 403
    for invalid in (
        {**body, "accent_color": "#12345G"},
        {**body, "accent_color": "1a2b3c"},
        {**body, "display_name": "   "},
        {**body, "display_name": "Line\nbreak"},
        {**body, "display_name": "x" * 101},
        {**body, "logo": "none"},
    ):
        assert owner.put(branding_url(w.a), json=invalid).status_code == 422, invalid
    saved = owner.put(branding_url(w.a), json=body)
    assert saved.status_code == 200
    assert (saved.json()["display_name"], saved.json()["accent_color"]) == (
        "Synthetic Studio",
        "#1A2B3C",
    )
    renamed = admin.put(branding_url(w.a), json={**body, "display_name": "Synthetic Two"})
    assert renamed.status_code == 200
    for reader in (owner, analyst, viewer):
        view = reader.get(branding_url(w.a)).json()
        assert view["configured"] is True and view["display_name"] == "Synthetic Two"
    assert audited(w) == 2


def test_rv17_logo(authenticated_world):
    w = authenticated_world
    owner, analyst, viewer = (w.signed_in(name) for name in ("owner_a", "analyst", "viewer"))
    image = png(width=64, height=32)
    response = put_logo(owner, w.a, image)
    assert response.status_code == 409 and response.json()["error"] == "branding_profile_required"
    owner.put(
        branding_url(w.a), json={"display_name": "Synthetic Studio", "accent_color": "#000000"}
    )
    assert put_logo(analyst, w.a, image).status_code == 403
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><script/></svg>' * 2
    response = put_logo(owner, w.a, svg, "image/svg+xml")
    assert response.status_code == 415 and response.json()["error"] == "unsupported_media_type"
    for data in (svg, image[:-1] + bytes([image[-1] ^ 1]), png(width=1025)):
        response = put_logo(owner, w.a, data)
        assert response.status_code == 422 and response.json()["error"] == "invalid_png"
    oversized = png(
        chunks=[
            (b"IHDR", image[16:29]),
            (b"IDAT", zlib.compress(bytes(4)) + bytes(256 * 1024)),
            (b"IEND", b""),
        ]
    )
    response = put_logo(owner, w.a, oversized)
    assert response.status_code == 413 and response.json()["error"] == "request_too_large"
    saved = put_logo(owner, w.a, image)
    assert saved.status_code == 200
    assert saved.json()["logo"] == {"width": 64, "height": 32, "byte_size": len(image)}
    served = viewer.get(f"{branding_url(w.a)}/logo")
    assert served.status_code == 200 and served.content == image
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-security-policy"] == "default-src 'none'"
    assert served.headers["cache-control"] == "no-store"
    assert analyst.delete(f"{branding_url(w.a)}/logo").status_code == 403
    removed = owner.delete(f"{branding_url(w.a)}/logo")
    assert removed.status_code == 200 and removed.json()["logo"] is None
    response = viewer.get(f"{branding_url(w.a)}/logo")
    assert response.status_code == 404 and response.json()["error"] == "logo_not_found"
    assert owner.delete(f"{branding_url(w.a)}/logo").status_code == 200
    assert audited(w) == 3  # the profile, the logo and its removal


def test_rv17_emails_carry_the_display_name(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    owner.put(
        branding_url(w.a), json={"display_name": "Synthetic Studio", "accent_color": "#123456"}
    )
    item = scheduled(owner, w, schedule_body(bodies(w)["social"], recipients=[str(w.viewer)]))
    due(w, item["id"])
    assert worker(w, api)["notified"] == 1
    assert process_mail(w.db.runtime, api.config)["delivered"] == 1
    (path,) = api.config.mail_directory.glob("*.eml")
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    body = message.get_body().get_content().replace(chr(13) + chr(10), chr(10))
    assert body.startswith("Synthetic Studio\n\n")
    assert "Synthetic Agency A" not in body


def test_rv19_isolation(authenticated_world):
    w = authenticated_world
    owner, other, outsider = (w.signed_in(name) for name in ("owner_a", "owner_b", "outsider"))
    owner.put(
        branding_url(w.a), json={"display_name": "Synthetic Studio", "accent_color": "#123456"}
    )
    put_logo(owner, w.a, png())
    other.put(branding_url(w.b), json={"display_name": "Other Studio", "accent_color": "#654321"})
    export = created(owner, w, bodies(w)["revenue"])
    schedule = scheduled(owner, w, schedule_body(bodies(w)["revenue"]))
    for reader in (other, outsider):
        assert reader.get(branding_url(w.a)).status_code == 403
        assert reader.get(f"{branding_url(w.a)}/logo").status_code == 403
        assert (
            reader.put(
                branding_url(w.a), json={"display_name": "Taken", "accent_color": "#000000"}
            ).status_code
            == 403
        )
        assert put_logo(reader, w.a, png()).status_code == 403
        assert reader.get(exports_url(w)).status_code == 403
        assert download(reader, w, export["id"]).status_code == 403
        assert reader.get(f"{schedules_url(w)}/{schedule['id']}").status_code == 403
    # Agency B's members see their own profile only.
    assert outsider.get(branding_url(w.b)).json()["display_name"] == "Other Studio"
    assert other.get(f"{branding_url(w.b)}/logo").status_code == 404
    # A foreign export ID answers the same refusal as an unknown one.
    unknown = owner.get(f"{exports_url(w, agency=w.b, client=w.b1)}/{export['id']}")
    assert unknown.status_code == 403
