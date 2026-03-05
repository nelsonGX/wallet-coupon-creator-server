"""
Build and sign Apple Wallet .pkpass bundles using py-pkpass.
"""

import io
import json
import os
import tempfile

from PIL import Image
from py_pkpass.models import Barcode, BarcodeFormat, Coupon, Field, Pass

PASS_TYPE_IDENTIFIER = "pass.com.nelsongx.apps.coupon-creator"
TEAM_IDENTIFIER = "G4LXL97NF9"
WEB_SERVICE_URL = os.getenv("WEB_SERVICE_URL", "https://example.com/api")

# Paths written at startup from the .p12
_cert_pem_path: str = ""
_key_pem_path: str = ""
_wwdr_pem_path: str = ""
_key_password: str = ""


def load_certificates() -> None:
    """Extract cert + key PEM files from the .p12 at startup."""
    global _cert_pem_path, _key_pem_path, _wwdr_pem_path, _key_password

    p12_path = os.environ.get("PASS_CERTIFICATE_PATH", "certs/pass.p12")
    _key_password = os.environ.get("PASS_CERTIFICATE_PASSWORD", "")
    _wwdr_pem_path = os.environ.get("WWDR_CERTIFICATE_PATH", "certs/wwdr.pem")

    from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption

    with open(p12_path, "rb") as f:
        p12_data = f.read()

    p12_password = _key_password.encode() if _key_password else None
    private_key, certificate, _ = pkcs12.load_key_and_certificates(p12_data, p12_password)

    cert_pem = certificate.public_bytes(Encoding.PEM)
    key_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())

    # Write to named temp files that persist for the process lifetime
    cert_fd, _cert_pem_path = tempfile.mkstemp(suffix="_pass_cert.pem")
    key_fd, _key_pem_path = tempfile.mkstemp(suffix="_pass_key.pem")

    with os.fdopen(cert_fd, "wb") as f:
        f.write(cert_pem)
    with os.fdopen(key_fd, "wb") as f:
        f.write(key_pem)


def _rgb_string(r: float, g: float, b: float) -> str:
    return f"rgb({round(r * 255)}, {round(g * 255)}, {round(b * 255)})"


def _solid_png(width: int, height: int, r: float, g: float, b: float) -> bytes:
    img = Image.new("RGB", (width, height), (round(r * 255), round(g * 255), round(b * 255)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_pkpass(pass_data: dict, authentication_token: str) -> bytes:
    bg_r = pass_data.get("bg_red", 0.0)
    bg_g = pass_data.get("bg_green", 0.0)
    bg_b = pass_data.get("bg_blue", 0.0)
    fg_r = pass_data.get("fg_red", 1.0)
    fg_g = pass_data.get("fg_green", 1.0)
    fg_b = pass_data.get("fg_blue", 1.0)
    lg_r = pass_data.get("label_red", fg_r)
    lg_g = pass_data.get("label_green", fg_g)
    lg_b = pass_data.get("label_blue", fg_b)

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

    status = "Active" if use_count < max_use else "Used Up"

    # Build coupon pass info
    coupon = Coupon()
    coupon.addHeaderField("discount", discount, "DISCOUNT")
    coupon.addPrimaryField("title", title, "COUPON")

    usage_field = Field("usage", f"{use_count}/{max_use}", "USES")
    usage_field.changeMessage = "Usage updated to %@"
    status_field = Field("status", status, "STATUS")
    status_field.changeMessage = "Status changed to %@"
    coupon.secondaryFields.append(usage_field)
    coupon.secondaryFields.append(status_field)

    coupon.addAuxiliaryField("rechargeable", "Yes" if is_rechargeable else "No", "RECHARGEABLE")

    coupon.addBackField("desc", description, "Description")
    coupon.addBackField("maxUses", str(max_use), "Maximum Uses")
    coupon.addBackField("currentUses", str(use_count), "Current Uses")
    coupon.addBackField("keepAfterUse", "Yes" if keep_after_used_up else "No", "Keep After Used Up")

    # Build the Pass object
    passfile = Pass(
        coupon,
        passTypeIdentifier=PASS_TYPE_IDENTIFIER,
        organizationName=organization_name,
        teamIdentifier=TEAM_IDENTIFIER,
    )
    passfile.serialNumber = coupon_id
    passfile.description = title
    passfile.logoText = organization_name
    passfile.backgroundColor = _rgb_string(bg_r, bg_g, bg_b)
    passfile.foregroundColor = _rgb_string(fg_r, fg_g, fg_b)
    passfile.labelColor = _rgb_string(lg_r, lg_g, lg_b)
    passfile.authenticationToken = authentication_token
    passfile.webServiceURL = WEB_SERVICE_URL.rstrip("/") + "/"

    if expiration_date:
        passfile.expirationDate = expiration_date

    passfile.barcode = Barcode(message=coupon_id, format=BarcodeFormat.QR)

    # Add placeholder images
    for name, size in [
        ("icon.png", 29), ("icon@2x.png", 58), ("icon@3x.png", 87),
        ("logo.png", 50), ("logo@2x.png", 100), ("logo@3x.png", 150),
    ]:
        passfile.addFile(name, io.BytesIO(_solid_png(size, size, bg_r, bg_g, bg_b)))

    # Sign and return bytes
    zip_buf = io.BytesIO()
    passfile.create(_cert_pem_path, _key_pem_path, _wwdr_pem_path, _key_password, zip_buf)
    return zip_buf.getvalue()
