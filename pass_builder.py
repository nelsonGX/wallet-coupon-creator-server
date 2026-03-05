"""
Build and sign Apple Wallet .pkpass bundles.
"""

import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timezone

from PIL import Image
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives.serialization.pkcs7 import (
    PKCS7SignatureBuilder,
    PKCS7Options,
)

PASS_TYPE_IDENTIFIER = "pass.com.nelsongx.apps.coupon-creator"
TEAM_IDENTIFIER = "G4LXL97NF9"
WEB_SERVICE_URL = os.getenv("WEB_SERVICE_URL", "https://example.com/api")

_cert_pem: bytes | None = None
_key_pem: bytes | None = None
_wwdr_cert: x509.Certificate | None = None
_pass_cert: x509.Certificate | None = None
_pass_key = None


def load_certificates() -> None:
    """Load and cache certificates from disk at startup."""
    global _cert_pem, _key_pem, _wwdr_cert, _pass_cert, _pass_key

    p12_path = os.environ.get("PASS_CERTIFICATE_PATH", "certs/pass.p12")
    p12_password_str = os.environ.get("PASS_CERTIFICATE_PASSWORD", "")
    wwdr_path = os.environ.get("WWDR_CERTIFICATE_PATH", "certs/wwdr.pem")

    with open(p12_path, "rb") as f:
        p12_data = f.read()

    p12_password = p12_password_str.encode() if p12_password_str else None
    private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
        p12_data, p12_password
    )

    _pass_key = private_key
    _pass_cert = certificate

    with open(wwdr_path, "rb") as f:
        wwdr_data = f.read()
    _wwdr_cert = x509.load_pem_x509_certificate(wwdr_data)


def _rgb_string(r: float, g: float, b: float) -> str:
    ri = round(r * 255)
    gi = round(g * 255)
    bi = round(b * 255)
    return f"rgb({ri}, {gi}, {bi})"


def _make_solid_png(width: int, height: int, r: float, g: float, b: float) -> bytes:
    ri = round(r * 255)
    gi = round(g * 255)
    bi = round(b * 255)
    img = Image.new("RGB", (width, height), color=(ri, gi, bi))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _sign_manifest(manifest_bytes: bytes) -> bytes:
    """Create a PKCS#7 detached DER signature of the manifest."""
    builder = PKCS7SignatureBuilder().set_data(manifest_bytes)
    builder = builder.add_signer(_pass_cert, _pass_key, hashes.SHA256())
    # Include WWDR as an additional certificate
    builder = builder.add_certificate(_wwdr_cert)
    signed = builder.sign(
        serialization.Encoding.DER,
        [PKCS7Options.DetachedSignature, PKCS7Options.NoCerts],
    )
    return signed


def build_pkpass(pass_data: dict, authentication_token: str) -> bytes:
    """
    Build a signed .pkpass ZIP bundle from the given pass data dict.

    pass_data keys: title, description, discount, organization_name, use_count,
    max_use, is_rechargeable, keep_after_used_up, expiration_date, coupon_id,
    bg_red, bg_green, bg_blue, fg_red, fg_green, fg_blue, barcode_message
    """
    bg_r = pass_data.get("bg_red", 0.0)
    bg_g = pass_data.get("bg_green", 0.0)
    bg_b = pass_data.get("bg_blue", 0.0)
    fg_r = pass_data.get("fg_red", 1.0)
    fg_g = pass_data.get("fg_green", 1.0)
    fg_b = pass_data.get("fg_blue", 1.0)

    use_count = pass_data.get("use_count", 0)
    max_use = pass_data.get("max_use", 1)
    is_rechargeable = pass_data.get("is_rechargeable", False)
    keep_after_used_up = pass_data.get("keep_after_used_up", True)
    title = pass_data.get("title", "")
    description = pass_data.get("description", "")
    discount = pass_data.get("discount", "")
    organization_name = pass_data.get("organization_name", "Coupon Creator")
    coupon_id = pass_data.get("coupon_id", "")
    expiration_date = pass_data.get("expiration_date")
    barcode_message = pass_data.get("barcode_message", "{}")

    status = "Active" if use_count < max_use else "Used Up"

    pass_json_dict: dict = {
        "formatVersion": 1,
        "passTypeIdentifier": PASS_TYPE_IDENTIFIER,
        "teamIdentifier": TEAM_IDENTIFIER,
        "serialNumber": coupon_id,
        "authenticationToken": authentication_token,
        "webServiceURL": f"{WEB_SERVICE_URL.rstrip('/')}/",
        "organizationName": organization_name,
        "description": title,
        "logoText": organization_name,
        "foregroundColor": _rgb_string(fg_r, fg_g, fg_b),
        "backgroundColor": _rgb_string(bg_r, bg_g, bg_b),
        "coupon": {
            "headerFields": [
                {"key": "discount", "label": "DISCOUNT", "value": discount}
            ],
            "primaryFields": [
                {"key": "title", "label": "COUPON", "value": title}
            ],
            "secondaryFields": [
                {
                    "key": "usage",
                    "label": "USES",
                    "value": f"{use_count}/{max_use}",
                    "changeMessage": "Usage updated to %@",
                },
                {
                    "key": "status",
                    "label": "STATUS",
                    "value": status,
                    "changeMessage": "Status changed to %@",
                },
            ],
            "auxiliaryFields": [
                {
                    "key": "rechargeable",
                    "label": "RECHARGEABLE",
                    "value": "Yes" if is_rechargeable else "No",
                }
            ],
            "backFields": [
                {"key": "desc", "label": "Description", "value": description},
                {"key": "maxUses", "label": "Maximum Uses", "value": max_use},
                {"key": "currentUses", "label": "Current Uses", "value": use_count},
                {
                    "key": "keepAfterUse",
                    "label": "Keep After Used Up",
                    "value": "Yes" if keep_after_used_up else "No",
                },
            ],
        },
        "barcodes": [
            {
                "format": "PKBarcodeFormatQR",
                "message": barcode_message,
                "messageEncoding": "iso-8859-1",
            }
        ],
    }

    if expiration_date:
        pass_json_dict["expirationDate"] = expiration_date

    pass_json_bytes = json.dumps(pass_json_dict, indent=2).encode("utf-8")

    # Build images
    images: dict[str, bytes] = {
        "icon.png": _make_solid_png(29, 29, bg_r, bg_g, bg_b),
        "icon@2x.png": _make_solid_png(58, 58, bg_r, bg_g, bg_b),
        "icon@3x.png": _make_solid_png(87, 87, bg_r, bg_g, bg_b),
        "logo.png": _make_solid_png(50, 50, bg_r, bg_g, bg_b),
        "logo@2x.png": _make_solid_png(100, 100, bg_r, bg_g, bg_b),
        "logo@3x.png": _make_solid_png(150, 150, bg_r, bg_g, bg_b),
    }

    # Build manifest
    manifest: dict[str, str] = {"pass.json": _sha1(pass_json_bytes)}
    for name, data in images.items():
        manifest[name] = _sha1(data)
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

    # Sign manifest
    signature_bytes = _sign_manifest(manifest_bytes)

    # Pack into ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pass.json", pass_json_bytes)
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("signature", signature_bytes)
        for name, data in images.items():
            zf.writestr(name, data)

    return zip_buf.getvalue()
