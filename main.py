import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel

load_dotenv()

from database import get_db, init_db
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

def _pass_data_from_request(req: PassRequest) -> dict:
    return {
        "title": req.title,
        "description": req.description,
        "discount": req.discount,
        "organization_name": req.organizationName,
        "use_count": req.useCount,
        "max_use": req.maxUse,
        "is_rechargeable": req.isRechargeable,
        "keep_after_used_up": req.keepAfterUsedUp,
        "expiration_date": req.expirationDate,
        "coupon_id": req.couponID,
        "bg_red": req.backgroundColor.red,
        "bg_green": req.backgroundColor.green,
        "bg_blue": req.backgroundColor.blue,
        "fg_red": req.foregroundColor.red,
        "fg_green": req.foregroundColor.green,
        "fg_blue": req.foregroundColor.blue,
        "barcode_message": req.model_dump_json(),
    }


def _upsert_pass(req: PassRequest) -> str:
    """Upsert pass into DB, returning the authentication_token."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT authentication_token FROM passes WHERE serial_number = ?",
            (req.couponID,),
        ).fetchone()

        if existing:
            auth_token = existing["authentication_token"]
            conn.execute(
                """
                UPDATE passes SET
                    title = ?, description = ?, discount = ?, organization_name = ?,
                    use_count = ?, max_use = ?, is_rechargeable = ?, keep_after_used_up = ?,
                    expiration_date = ?, bg_red = ?, bg_green = ?, bg_blue = ?,
                    fg_red = ?, fg_green = ?, fg_blue = ?, last_updated = ?
                WHERE serial_number = ?
                """,
                (
                    req.title, req.description, req.discount, req.organizationName,
                    req.useCount, req.maxUse, int(req.isRechargeable), int(req.keepAfterUsedUp),
                    req.expirationDate,
                    req.backgroundColor.red, req.backgroundColor.green, req.backgroundColor.blue,
                    req.foregroundColor.red, req.foregroundColor.green, req.foregroundColor.blue,
                    int(time.time()),
                    req.couponID,
                ),
            )
        else:
            auth_token = secrets.token_hex(16)
            conn.execute(
                """
                INSERT INTO passes (
                    serial_number, authentication_token, title, description, discount,
                    organization_name, use_count, max_use, is_rechargeable, keep_after_used_up,
                    expiration_date, bg_red, bg_green, bg_blue, fg_red, fg_green, fg_blue,
                    last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.couponID, auth_token, req.title, req.description, req.discount,
                    req.organizationName, req.useCount, req.maxUse, int(req.isRechargeable),
                    int(req.keepAfterUsedUp), req.expirationDate,
                    req.backgroundColor.red, req.backgroundColor.green, req.backgroundColor.blue,
                    req.foregroundColor.red, req.foregroundColor.green, req.foregroundColor.blue,
                    int(time.time()),
                ),
            )
    return auth_token


def _pkpass_response(pkpass_bytes: bytes) -> FastAPIResponse:
    return FastAPIResponse(
        content=pkpass_bytes,
        media_type="application/vnd.apple.pkpass",
        headers={"Content-Disposition": 'attachment; filename="coupon.pkpass"'},
    )


def _validate_auth_token(serial_number: str, auth_header: Optional[str]) -> None:
    if not auth_header or not auth_header.startswith("ApplePass "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    provided_token = auth_header[len("ApplePass "):]
    with get_db() as conn:
        row = conn.execute(
            "SELECT authentication_token FROM passes WHERE serial_number = ?",
            (serial_number,),
        ).fetchone()
    if not row or row["authentication_token"] != provided_token:
        raise HTTPException(status_code=401, detail="Invalid authentication token")


# ---------------------------------------------------------------------------
# Part 1: Pass Creation
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/sign-pass")
async def sign_pass(req: PassRequest):
    auth_token = _upsert_pass(req)
    pass_data = _pass_data_from_request(req)
    pkpass_bytes = build_pkpass(pass_data, auth_token)
    return _pkpass_response(pkpass_bytes)


@app.post("/update-pass")
async def update_pass(req: PassRequest):
    auth_token = _upsert_pass(req)
    pass_data = _pass_data_from_request(req)
    pkpass_bytes = build_pkpass(pass_data, auth_token)

    # Send push notifications
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.push_token, d.device_library_identifier, d.id as device_id
            FROM devices d
            JOIN registrations r ON r.device_id = d.id
            WHERE r.serial_number = ?
            """,
            (req.couponID,),
        ).fetchall()

    if rows:
        push_tokens = [r["push_token"] for r in rows]
        token_to_device = {r["push_token"]: r["device_id"] for r in rows}

        from apns import send_push_notifications
        invalid_tokens = await send_push_notifications(push_tokens)

        if invalid_tokens:
            with get_db() as conn:
                for token in invalid_tokens:
                    device_id = token_to_device.get(token)
                    if device_id:
                        # Remove registrations for this device first
                        conn.execute("DELETE FROM registrations WHERE device_id = ?", (device_id,))
                        # If no more registrations, remove the device
                        remaining = conn.execute(
                            "SELECT COUNT(*) as cnt FROM registrations WHERE device_id = ?",
                            (device_id,),
                        ).fetchone()
                        if remaining["cnt"] == 0:
                            conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))

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
    authorization: Optional[str] = Header(None),
):
    _validate_auth_token(serial_number, authorization)

    body = await request.json()
    push_token = body.get("pushToken", "")
    if not push_token:
        raise HTTPException(status_code=400, detail="Missing pushToken")

    with get_db() as conn:
        # Upsert device
        conn.execute(
            """
            INSERT INTO devices (device_library_identifier, push_token)
            VALUES (?, ?)
            ON CONFLICT(device_library_identifier) DO UPDATE SET push_token = excluded.push_token
            """,
            (device_library_identifier, push_token),
        )
        device_row = conn.execute(
            "SELECT id FROM devices WHERE device_library_identifier = ?",
            (device_library_identifier,),
        ).fetchone()
        device_id = device_row["id"]

        # Check if registration exists
        existing_reg = conn.execute(
            "SELECT id FROM registrations WHERE device_id = ? AND serial_number = ?",
            (device_id, serial_number),
        ).fetchone()

        if existing_reg:
            return Response(status_code=200)

        conn.execute(
            "INSERT INTO registrations (device_id, serial_number) VALUES (?, ?)",
            (device_id, serial_number),
        )

    return Response(status_code=201)


@app.get("/api/v1/devices/{device_library_identifier}/registrations/{pass_type_identifier}")
async def get_serial_numbers(
    device_library_identifier: str,
    pass_type_identifier: str,
    request: Request,
):
    passes_updated_since = request.query_params.get("passesUpdatedSince")

    with get_db() as conn:
        device_row = conn.execute(
            "SELECT id FROM devices WHERE device_library_identifier = ?",
            (device_library_identifier,),
        ).fetchone()

        if not device_row:
            return Response(status_code=204)

        device_id = device_row["id"]

        if passes_updated_since:
            try:
                since_ts = int(passes_updated_since)
            except ValueError:
                since_ts = 0
            rows = conn.execute(
                """
                SELECT p.serial_number, p.last_updated
                FROM passes p
                JOIN registrations r ON r.serial_number = p.serial_number
                WHERE r.device_id = ? AND p.last_updated > ?
                """,
                (device_id, since_ts),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT p.serial_number, p.last_updated
                FROM passes p
                JOIN registrations r ON r.serial_number = p.serial_number
                WHERE r.device_id = ?
                """,
                (device_id,),
            ).fetchall()

    if not rows:
        return Response(status_code=204)

    serial_numbers = [r["serial_number"] for r in rows]
    last_updated = str(max(r["last_updated"] for r in rows))

    return {"serialNumbers": serial_numbers, "lastUpdated": last_updated}


@app.get("/api/v1/passes/{pass_type_identifier}/{serial_number}")
async def get_latest_pass(
    pass_type_identifier: str,
    serial_number: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    _validate_auth_token(serial_number, authorization)

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM passes WHERE serial_number = ?",
            (serial_number,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Pass not found")

    # Check If-Modified-Since
    if_modified_since = request.headers.get("If-Modified-Since")
    if if_modified_since:
        try:
            client_ts = int(if_modified_since)
            if row["last_updated"] <= client_ts:
                return Response(status_code=304)
        except ValueError:
            pass

    pass_data = {
        "title": row["title"],
        "description": row["description"],
        "discount": row["discount"],
        "organization_name": row["organization_name"],
        "use_count": row["use_count"],
        "max_use": row["max_use"],
        "is_rechargeable": bool(row["is_rechargeable"]),
        "keep_after_used_up": bool(row["keep_after_used_up"]),
        "expiration_date": row["expiration_date"],
        "coupon_id": row["serial_number"],
        "bg_red": row["bg_red"],
        "bg_green": row["bg_green"],
        "bg_blue": row["bg_blue"],
        "fg_red": row["fg_red"],
        "fg_green": row["fg_green"],
        "fg_blue": row["fg_blue"],
        "barcode_message": json.dumps({
            "title": row["title"],
            "description": row["description"],
            "discount": row["discount"],
            "organizationName": row["organization_name"],
            "useCount": row["use_count"],
            "maxUse": row["max_use"],
            "isRechargeable": bool(row["is_rechargeable"]),
            "keepAfterUsedUp": bool(row["keep_after_used_up"]),
            "expirationDate": row["expiration_date"],
            "couponID": row["serial_number"],
            "backgroundColor": {"red": row["bg_red"], "green": row["bg_green"], "blue": row["bg_blue"]},
            "foregroundColor": {"red": row["fg_red"], "green": row["fg_green"], "blue": row["fg_blue"]},
        }),
    }

    pkpass_bytes = build_pkpass(pass_data, row["authentication_token"])
    return _pkpass_response(pkpass_bytes)


@app.delete("/api/v1/devices/{device_library_identifier}/registrations/{pass_type_identifier}/{serial_number}")
async def unregister_device(
    device_library_identifier: str,
    pass_type_identifier: str,
    serial_number: str,
    authorization: Optional[str] = Header(None),
):
    _validate_auth_token(serial_number, authorization)

    with get_db() as conn:
        device_row = conn.execute(
            "SELECT id FROM devices WHERE device_library_identifier = ?",
            (device_library_identifier,),
        ).fetchone()

        if not device_row:
            return Response(status_code=200)

        device_id = device_row["id"]
        conn.execute(
            "DELETE FROM registrations WHERE device_id = ? AND serial_number = ?",
            (device_id, serial_number),
        )

        remaining = conn.execute(
            "SELECT COUNT(*) as cnt FROM registrations WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if remaining["cnt"] == 0:
            conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    return Response(status_code=200)


@app.post("/api/v1/log")
async def log_errors(request: Request):
    body = await request.json()
    logs = body.get("logs", [])
    for msg in logs:
        logger.warning("[Apple Wallet] %s", msg)
    return Response(status_code=200)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
