import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from database import Device, Pass, Registration, ShareToken, get_session
from pass_builder import build_pkpass
from schemas import PassRequest
from services.pass_service import pass_data_from_db, pkpass_response, upsert_pass
from apns import send_push_notifications

router = APIRouter()


def _parse_pass_request(data: str = Form(...)) -> PassRequest:
    try:
        return PassRequest.model_validate(json.loads(data))
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.post("/sign-pass")
async def sign_pass(
    data: str = Form(...),
    icon: Optional[UploadFile] = File(default=None),
    session: Session = Depends(get_session),
):
    req = _parse_pass_request(data)
    print("Signing pass:", req.couponID)
    pass_ = upsert_pass(req, session)
    if icon is not None:
        if not icon.content_type or not icon.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="icon must be an image")
        pass_.icon_image = await icon.read()
        session.add(pass_)
        session.commit()
        session.refresh(pass_)
    pkpass_bytes = build_pkpass(pass_data_from_db(pass_), pass_.authentication_token)
    return pkpass_response(pkpass_bytes)


@router.post("/update-pass")
async def update_pass(
    data: str = Form(...),
    icon: Optional[UploadFile] = File(default=None),
    session: Session = Depends(get_session),
):
    req = _parse_pass_request(data)
    print("Updating pass:", req.couponID)
    pass_ = upsert_pass(req, session)
    if icon is not None:
        if not icon.content_type or not icon.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="icon must be an image")
        pass_.icon_image = await icon.read()
        session.add(pass_)
        session.commit()
        session.refresh(pass_)
    pkpass_bytes = build_pkpass(pass_data_from_db(pass_), pass_.authentication_token)

    registrations = session.exec(
        select(Registration).where(Registration.serial_number == req.couponID)
    ).all()

    if registrations:
        devices = session.exec(
            select(Device)
            .join(Registration, Registration.device_id == Device.id) # type: ignore
            .where(Registration.serial_number == req.couponID)
        ).all()
        push_tokens = [d.push_token for d in devices]
        token_to_device = {d.push_token: d for d in devices}

        print("Sending push notifications to:", push_tokens, "tokens for devices:", token_to_device)

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

    return pkpass_response(pkpass_bytes)


@router.post("/create-share-link/{serial_number}")
async def create_share_link(
    serial_number: str,
    session: Session = Depends(get_session),
):
    pass_ = session.get(Pass, serial_number)
    if not pass_:
        raise HTTPException(status_code=404, detail="Pass not found")

    token = ShareToken(serial_number=serial_number)
    session.add(token)
    session.commit()
    session.refresh(token)

    return {"token": token.token}


@router.get("/share/{token}")
async def redeem_share_link(
    token: str,
    session: Session = Depends(get_session),
):
    share_token = session.get(ShareToken, token)
    if not share_token:
        raise HTTPException(status_code=404, detail="Invalid share link")
    if share_token.used:
        raise HTTPException(status_code=410, detail="This share link has already been used")

    pass_ = session.get(Pass, share_token.serial_number)
    if not pass_:
        raise HTTPException(status_code=404, detail="Pass not found")

    pkpass_bytes = build_pkpass(pass_data_from_db(pass_), pass_.authentication_token)
    return pkpass_response(pkpass_bytes)
