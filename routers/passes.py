from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from database import Device, Registration, get_session
from pass_builder import build_pkpass
from schemas import PassRequest
from services.pass_service import pass_data_from_db, pkpass_response, upsert_pass
from apns import send_push_notifications

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.post("/sign-pass")
async def sign_pass(req: PassRequest, session: Session = Depends(get_session)):
    print("Signing pass:", req.couponID)
    pass_ = upsert_pass(req, session)
    pkpass_bytes = build_pkpass(pass_data_from_db(pass_), pass_.authentication_token)
    return pkpass_response(pkpass_bytes)


@router.post("/update-pass")
async def update_pass(req: PassRequest, session: Session = Depends(get_session)):
    print("Updating pass:", req.couponID)
    pass_ = upsert_pass(req, session)
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
