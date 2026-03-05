import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlmodel import Session, select

from database import Device, Pass, Registration, get_session
from pass_builder import build_pkpass
from services.pass_service import pass_data_from_db, pkpass_response, validate_auth_token

router = APIRouter(prefix="/v1")
logger = logging.getLogger(__name__)


@router.post("/devices/{device_library_identifier}/registrations/{pass_type_identifier}/{serial_number}")
async def register_device(
    device_library_identifier: str,
    pass_type_identifier: str,
    serial_number: str,
    request: Request,
    session: Session = Depends(get_session),
    authorization: Optional[str] = Header(None),
):
    validate_auth_token(serial_number, authorization, session)

    body = await request.json()
    push_token = body.get("pushToken", "")
    if not push_token:
        raise HTTPException(status_code=400, detail="Missing pushToken")

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

    existing_reg = session.exec(
        select(Registration).where(
            Registration.device_id == device.id,
            Registration.serial_number == serial_number,
        )
    ).first()

    if existing_reg:
        return Response(status_code=200)

    if device.id is None:
        raise HTTPException(status_code=500, detail="Device ID is missing")

    session.add(Registration(device_id=device.id, serial_number=serial_number))
    session.commit()
    return Response(status_code=201)


@router.get("/devices/{device_library_identifier}/registrations/{pass_type_identifier}")
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
        .join(Registration, Registration.serial_number == Pass.serial_number) # type: ignore
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


@router.get("/passes/{pass_type_identifier}/{serial_number}")
async def get_latest_pass(
    pass_type_identifier: str,
    serial_number: str,
    request: Request,
    session: Session = Depends(get_session),
    authorization: Optional[str] = Header(None),
):
    pass_ = validate_auth_token(serial_number, authorization, session)

    if_modified_since = request.headers.get("If-Modified-Since")
    if if_modified_since:
        try:
            if pass_.last_updated <= int(if_modified_since):
                return Response(status_code=304)
        except ValueError:
            pass

    pkpass_bytes = build_pkpass(pass_data_from_db(pass_), pass_.authentication_token)
    return pkpass_response(pkpass_bytes)


@router.delete("/devices/{device_library_identifier}/registrations/{pass_type_identifier}/{serial_number}")
async def unregister_device(
    device_library_identifier: str,
    pass_type_identifier: str,
    serial_number: str,
    session: Session = Depends(get_session),
    authorization: Optional[str] = Header(None),
):
    validate_auth_token(serial_number, authorization, session)

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


@router.post("/log")
async def log_errors(request: Request):
    body = await request.json()
    for msg in body.get("logs", []):
        logger.warning("[Apple Wallet] %s", msg)
    return Response(status_code=200)
