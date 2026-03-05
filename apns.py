"""
Send Apple Push Notification Service (APNs) push notifications for pass updates.

Pass update notifications use the production APNs endpoint and the pass certificate.
The payload is an empty JSON object {} as required by the Wallet protocol.
"""

import json
import logging
import os
import time

import httpx

APNS_HOST = "https://api.push.apple.com"
PASS_TYPE_IDENTIFIER = "pass.com.nelsongx.apps.coupon-creator"

logger = logging.getLogger(__name__)


def _load_p12_pem() -> tuple[bytes, bytes]:
    """Return (cert_pem, key_pem) extracted from the .p12 file."""
    from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption

    p12_path = os.environ.get("PASS_CERTIFICATE_PATH", "certs/pass.p12")
    p12_password_str = os.environ.get("PASS_CERTIFICATE_PASSWORD", "")

    with open(p12_path, "rb") as f:
        p12_data = f.read()

    p12_password = p12_password_str.encode() if p12_password_str else None
    private_key, certificate, _ = pkcs12.load_key_and_certificates(p12_data, p12_password)

    cert_pem = certificate.public_bytes(Encoding.PEM)
    key_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
    return cert_pem, key_pem


async def send_push_notifications(push_tokens: list[str]) -> list[str]:
    """
    Send APNs push notifications to all given push tokens.

    Returns a list of invalid push tokens that should be removed from the DB.
    """
    if not push_tokens:
        return []

    try:
        cert_pem, key_pem = _load_p12_pem()
    except Exception as e:
        logger.error("Failed to load certificates for APNs: %s", e)
        return []

    invalid_tokens: list[str] = []

    # httpx with HTTP/2 and mutual TLS
    async with httpx.AsyncClient(
        http2=True,
        cert=(
            _write_temp(cert_pem, "cert.pem"),
            _write_temp(key_pem, "key.pem"),
        ),
        timeout=10.0,
    ) as client:
        for token in push_tokens:
            url = f"{APNS_HOST}/3/device/{token}"
            headers = {
                "apns-topic": PASS_TYPE_IDENTIFIER,
                "apns-push-type": "background",
            }
            payload = json.dumps({}).encode()
            try:
                response = await client.post(url, content=payload, headers=headers)
                if response.status_code == 200:
                    logger.info("APNs push sent to %s", token)
                elif response.status_code == 410:
                    # Token is no longer valid
                    logger.warning("APNs token gone (410): %s", token)
                    invalid_tokens.append(token)
                elif response.status_code == 400:
                    body = response.json()
                    reason = body.get("reason", "")
                    if reason in ("BadDeviceToken", "Unregistered"):
                        invalid_tokens.append(token)
                    logger.warning("APNs 400 for %s: %s", token, reason)
                else:
                    logger.warning("APNs unexpected status %d for %s", response.status_code, token)
            except Exception as e:
                logger.error("APNs request failed for %s: %s", token, e)

    return invalid_tokens


import tempfile
import os as _os

_temp_files: list[str] = []


def _write_temp(data: bytes, suffix: str) -> str:
    """Write bytes to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=f"_{suffix}")
    with _os.fdopen(fd, "wb") as f:
        f.write(data)
    _temp_files.append(path)
    return path


def cleanup_temp_files() -> None:
    for path in _temp_files:
        try:
            _os.remove(path)
        except OSError:
            pass
    _temp_files.clear()
