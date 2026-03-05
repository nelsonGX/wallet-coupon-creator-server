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
        "barcode_message": json.dumps({
            "title": row.title,
            "description": row.description,
            "discount": row.discount,
            "organizationName": row.organization_name,
            "useCount": row.use_count,
            "maxUse": row.max_use,
            "isRechargeable": row.is_rechargeable,
            "keepAfterUsedUp": row.keep_after_used_up,
            "expirationDate": row.expiration_date,
            "couponID": row.serial_number,
            "backgroundColor": {"red": row.bg_red, "green": row.bg_green, "blue": row.bg_blue},
            "foregroundColor": {"red": row.fg_red, "green": row.fg_green, "blue": row.fg_blue},
        }),
    }


def upsert_pass(req: PassRequest, session: Session) -> Pass:
    existing = session.get(Pass, req.couponID)

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
