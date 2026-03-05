import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel
from sqlmodel import Session, select

load_dotenv()

from database import Device, Pass, Registration, get_session, init_db
from pass_builder import build_pkpass, load_certificates

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)



@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    load_certificates()
    yield


app = FastAPI(
    title="Wallet Coupon Creator Server",
    description="Apple Wallet .pkpass signing and auto-update server",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ColorComponent(BaseModel):
    red: float
    green: float
    blue: float


class PassRequest(BaseModel):
    title: str
    description: str = ""
    discount: str = ""
    organizationName: str = "Coupon Creator"
    useCount: int = 0
    maxUse: int = 1
    isRechargeable: bool = False
    keepAfterUsedUp: bool = True
    expirationDate: Optional[str] = None
    couponID: str
    backgroundColor: ColorComponent
    foregroundColor: ColorComponent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pass_data_from_db(row: Pass) -> dict:
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


def _upsert_pass(req: PassRequest, session: Session) -> Pass:
    """Upsert pass into DB, returning the Pass ORM object."""
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


def _pkpass_response(pkpass_bytes: bytes) -> FastAPIResponse:
    return FastAPIResponse(
        content=pkpass_bytes,
        media_type="application/vnd.apple.pkpass",
        headers={"Content-Disposition": 'attachment; filename="coupon.pkpass"'},
    )


def _validate_auth_token(serial_number: str, auth_header: Optional[str], session: Session) -> Pass:
    if not auth_header or not auth_header.startswith("ApplePass "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    provided_token = auth_header[len("ApplePass "):]
    pass_ = session.get(Pass, serial_number)
    if not pass_ or pass_.authentication_token != provided_token:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    return pass_


# ---------------------------------------------------------------------------
# Part 1: Pass Creation
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/sign-pass")
async def sign_pass(req: PassRequest, session: Session = Depends(get_session)):
    pass_ = _upsert_pass(req, session)
    pkpass_bytes = build_pkpass(_pass_data_from_db(pass_), pass_.authentication_token)
    return _pkpass_response(pkpass_bytes)


@app.post("/update-pass")
async def update_pass(req: PassRequest, session: Session = Depends(get_session)):
    pass_ = _upsert_pass(req, session)
    pkpass_bytes = build_pkpass(_pass_data_from_db(pass_), pass_.authentication_token)

    # Collect push tokens for registered devices
    registrations = session.exec(
        select(Registration).where(Registration.serial_number == req.couponID)
    ).all()

    if registrations:
        devices = session.exec(
            select(Device)
            .join(Registration, Registration.device_id == Device.id)
            .where(Registration.serial_number == req.couponID)
        ).all()
        push_tokens = [d.push_token for d in devices]
        token_to_device = {d.push_token: d for d in devices}

        from apns import send_push_notifications
        invalid_tokens = await send_push_notifications(push_tokens)

        for token in invalid_tokens:
            device = token_to_device.get(token)
            if device:
                device_regs = session.exec(
                    select(Registration).where(Registration.device_id == device.id)
                ).all()
                for reg in device_regs:
                    session.delete(reg)
                session.delete(device)
        if invalid_tokens:
            session.commit()

    return _pkpass_response(pkpass_bytes)


# ---------------------------------------------------------------------------
# Part 2: Apple Wallet Web Service Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/devices/{device_library_identifier}/registrations/{pass_type_identifier}/{serial_number}")
async def register_device(
    device_library_identifier: str,
    pass_type_identifier: str,
    serial_number: str,
    request: Request,
    session: Session = Depends(get_session),
    authorization: Optional[str] = Header(None),
):
    _validate_auth_token(serial_number, authorization, session)

    body = await request.json()
    push_token = body.get("pushToken", "")
    if not push_token:
        raise HTTPException(status_code=400, detail="Missing pushToken")

    # Upsert device
    device = session.exec(
        select(Device).where(Device.device_library_identifier == device_library_identifier)
    ).first()

    if device:
        device.push_token = push_token
        session.add(device)
    else:
        device = Device(device_library_identifier=device_library_identifier, push_token=push_token)
        session.add(device)

    session.commit()
    session.refresh(device)

    # Check for existing registration
    existing_reg = session.exec(
        select(Registration).where(
            Registration.device_id == device.id,
            Registration.serial_number == serial_number,
        )
    ).first()

    if existing_reg:
        return Response(status_code=200)

    session.add(Registration(device_id=device.id, serial_number=serial_number))
    session.commit()
    return Response(status_code=201)


@app.get("/api/v1/devices/{device_library_identifier}/registrations/{pass_type_identifier}")
async def get_serial_numbers(
    device_library_identifier: str,
    pass_type_identifier: str,
    request: Request,
    session: Session = Depends(get_session),
):
    device = session.exec(
        select(Device).where(Device.device_library_identifier == device_library_identifier)
    ).first()

    if not device:
        return Response(status_code=204)

    passes_updated_since = request.query_params.get("passesUpdatedSince")

    query = (
        select(Pass)
        .join(Registration, Registration.serial_number == Pass.serial_number)
        .where(Registration.device_id == device.id)
    )
    if passes_updated_since:
        try:
            since_ts = int(passes_updated_since)
            query = query.where(Pass.last_updated > since_ts)
        except ValueError:
            pass

    passes = session.exec(query).all()

    if not passes:
        return Response(status_code=204)

    return {
        "serialNumbers": [p.serial_number for p in passes],
        "lastUpdated": str(max(p.last_updated for p in passes)),
    }


@app.get("/api/v1/passes/{pass_type_identifier}/{serial_number}")
async def get_latest_pass(
    pass_type_identifier: str,
    serial_number: str,
    request: Request,
    session: Session = Depends(get_session),
    authorization: Optional[str] = Header(None),
):
    pass_ = _validate_auth_token(serial_number, authorization, session)

    if_modified_since = request.headers.get("If-Modified-Since")
    if if_modified_since:
        try:
            if pass_.last_updated <= int(if_modified_since):
                return Response(status_code=304)
        except ValueError:
            pass

    pkpass_bytes = build_pkpass(_pass_data_from_db(pass_), pass_.authentication_token)
    return _pkpass_response(pkpass_bytes)


@app.delete("/api/v1/devices/{device_library_identifier}/registrations/{pass_type_identifier}/{serial_number}")
async def unregister_device(
    device_library_identifier: str,
    pass_type_identifier: str,
    serial_number: str,
    session: Session = Depends(get_session),
    authorization: Optional[str] = Header(None),
):
    _validate_auth_token(serial_number, authorization, session)

    device = session.exec(
        select(Device).where(Device.device_library_identifier == device_library_identifier)
    ).first()

    if not device:
        return Response(status_code=200)

    reg = session.exec(
        select(Registration).where(
            Registration.device_id == device.id,
            Registration.serial_number == serial_number,
        )
    ).first()

    if reg:
        session.delete(reg)
        session.commit()

    remaining = session.exec(
        select(Registration).where(Registration.device_id == device.id)
    ).all()

    if not remaining:
        session.delete(device)
        session.commit()

    return Response(status_code=200)


@app.post("/api/v1/log")
async def log_errors(request: Request):
    body = await request.json()
    for msg in body.get("logs", []):
        logger.warning("[Apple Wallet] %s", msg)
    return Response(status_code=200)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
