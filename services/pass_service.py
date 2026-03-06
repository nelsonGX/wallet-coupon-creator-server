import json
import secrets
import time
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import Response as FastAPIResponse
from sqlmodel import Session

from database import Device, Pass, Registration
from schemas import PassRequest


def pass_data_from_db(row: Pass) -> dict:
    return {
        "title": row.title,
        "description": row.description,
        "discount": row.discount,
        "organization_name": row.organization_name,
        "use_count": row.use_count,
        "max_use": row.max_use,
        "is_rechargeable": row.is_rechargeable,
        "keep_after_used_up": row.keep_after_used_up,
        "expiration_date": row.expiration_date,
        "coupon_id": row.serial_number,
        "bg_red": row.bg_red,
        "bg_green": row.bg_green,
        "bg_blue": row.bg_blue,
        "fg_red": row.fg_red,
        "fg_green": row.fg_green,
        "fg_blue": row.fg_blue,
        "lb_red": row.lb_red,
        "lb_green": row.lb_green,
        "lb_blue": row.lb_blue,
        "language": row.language,
        "icon_image": row.icon_image,
        "relevant_date": row.relevant_date,
        "locations": json.loads(row.locations_json) if row.locations_json else None,
        "ibeacons": json.loads(row.ibeacons_json) if row.ibeacons_json else None,
    }


def upsert_pass(req: PassRequest, session: Session) -> Pass:
    existing = session.get(Pass, req.couponID)

    locations_json = json.dumps([loc.model_dump(exclude_none=True) for loc in req.locations]) if req.locations else None
    ibeacons_json = json.dumps([b.model_dump(exclude_none=True) for b in req.ibeacons]) if req.ibeacons else None

    if existing:
        existing.title = req.title
        existing.description = req.description
        existing.discount = req.discount
        existing.organization_name = req.organizationName
        existing.use_count = req.useCount
        existing.max_use = req.maxUse
        existing.is_rechargeable = req.isRechargeable
        existing.keep_after_used_up = req.keepAfterUsedUp
        existing.expiration_date = req.expirationDate
        existing.bg_red = req.backgroundColor.red
        existing.bg_green = req.backgroundColor.green
        existing.bg_blue = req.backgroundColor.blue
        existing.fg_red = req.foregroundColor.red
        existing.fg_green = req.foregroundColor.green
        existing.fg_blue = req.foregroundColor.blue
        existing.lb_red = req.labelColor.red if req.labelColor else req.foregroundColor.red
        existing.lb_green = req.labelColor.green if req.labelColor else req.foregroundColor.green
        existing.lb_blue = req.labelColor.blue if req.labelColor else req.foregroundColor.blue
        existing.language = req.language
        existing.relevant_date = req.relevantDate
        existing.locations_json = locations_json
        existing.ibeacons_json = ibeacons_json
        existing.last_updated = int(time.time())
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    new_pass = Pass(
        serial_number=req.couponID,
        authentication_token=secrets.token_hex(16),
        title=req.title,
        description=req.description,
        discount=req.discount,
        organization_name=req.organizationName,
        use_count=req.useCount,
        max_use=req.maxUse,
        is_rechargeable=req.isRechargeable,
        keep_after_used_up=req.keepAfterUsedUp,
        expiration_date=req.expirationDate,
        bg_red=req.backgroundColor.red,
        bg_green=req.backgroundColor.green,
        bg_blue=req.backgroundColor.blue,
        fg_red=req.foregroundColor.red,
        fg_green=req.foregroundColor.green,
        fg_blue=req.foregroundColor.blue,
        lb_red=req.labelColor.red if req.labelColor else req.foregroundColor.red,
        lb_green=req.labelColor.green if req.labelColor else req.foregroundColor.green,
        lb_blue=req.labelColor.blue if req.labelColor else req.foregroundColor.blue,
        language=req.language,
        relevant_date=req.relevantDate,
        locations_json=locations_json,
        ibeacons_json=ibeacons_json,
        last_updated=int(time.time()),
    )
    session.add(new_pass)
    session.commit()
    session.refresh(new_pass)
    return new_pass


def pkpass_response(pkpass_bytes: bytes) -> FastAPIResponse:
    return FastAPIResponse(
        content=pkpass_bytes,
        media_type="application/vnd.apple.pkpass",
        headers={"Content-Disposition": 'attachment; filename="coupon.pkpass"'},
    )


def validate_auth_token(serial_number: str, auth_header: Optional[str], session: Session) -> Pass:
    if not auth_header or not auth_header.startswith("ApplePass "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    provided_token = auth_header[len("ApplePass "):]
    pass_ = session.get(Pass, serial_number)
    if not pass_ or pass_.authentication_token != provided_token:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    return pass_
