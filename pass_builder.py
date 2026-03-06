"""
Build and sign Apple Wallet .pkpass bundles using py-pkpass.
"""

import io
import os
import tempfile
from datetime import datetime, timezone

from PIL import Image
from py_pkpass.models import Barcode, BarcodeFormat, Coupon, Field, Pass

# Patch Field.json_dict to exclude empty changeMessage — iOS suppresses notifications for fields with changeMessage: ""
def _field_json_dict(self):
    d = dict(self.__dict__)
    if not d.get("changeMessage"):
        d.pop("changeMessage", None)
    return d
Field.json_dict = _field_json_dict

PASS_TYPE_IDENTIFIER = "pass.com.nelsongx.apps.coupon-creator"
TEAM_IDENTIFIER = "G4LXL97NF9"
WEB_SERVICE_URL = os.getenv("WEB_SERVICE_URL", "https://example.com/api")

# Paths written at startup from the .p12
_cert_pem_path: str = ""
_key_pem_path: str = ""
_wwdr_pem_path: str = ""
_key_password: str = ""

# ---------------------------------------------------------------------------
# Localization strings
# ---------------------------------------------------------------------------

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "label_discount": "DISCOUNT",
        "label_coupon": "COUPON",
        "label_uses": "USES",
        "label_status": "STATUS",
        "label_rechargeable": "RECHARGEABLE",
        "label_description": "Description",
        "label_max_uses": "Maximum Uses",
        "label_current_uses": "Current Uses",
        "label_keep_after_use": "Keep After Used Up",
        "label_expires": "Expires",
        "label_expire_date": "Expiration Date",
        "value_no_expiry": "No Expiration",
        "value_yes": "Yes",
        "value_no": "No",
        "value_expired": "EXPIRED",
        "change_message": "{title} coupon has been used. %@.",
        "change_message_left": " Uses Left"
    },
    "zh-TW": {
        "label_discount": "折扣",
        "label_coupon": "優惠券",
        "label_uses": "使用次數",
        "label_status": "剩餘次數",
        "label_rechargeable": "可充值",
        "label_description": "描述",
        "label_max_uses": "最大使用次數",
        "label_current_uses": "已使用次數",
        "label_keep_after_use": "用完後保留",
        "label_expires": "到期",
        "label_expire_date": "到期日",
        "value_no_expiry": "無效期限",
        "value_yes": "是",
        "value_no": "否",
        "value_expired": "已過期",
        "change_message": "{title} 優惠券已使用。剩餘 %@。",
        "change_message_left": " 次"
    },
}

def _t(lang: str, key: str) -> str:
    return _STRINGS.get(lang, _STRINGS["en"]).get(key, _STRINGS["en"][key])


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


def _resize_png(image_bytes: bytes, width: int, height: int) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    img = img.resize((width, height), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _is_expired(pass_data: dict) -> bool:
    """Return True if the pass should be voided due to expiration or usage."""
    # Check date expiration
    expiration_date = pass_data.get("expiration_date")
    if expiration_date:
        try:
            exp_dt = datetime.fromisoformat(expiration_date.replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp_dt:
                return True
        except ValueError:
            pass

    # Check used-up expiration
    use_count = pass_data.get("use_count", 0)
    max_use = pass_data.get("max_use", 1)
    keep_after_used_up = pass_data.get("keep_after_used_up", True)
    is_rechargeable = pass_data.get("is_rechargeable", False)
    if not keep_after_used_up and not is_rechargeable and use_count >= max_use:
        return True

    return False


def build_pkpass(pass_data: dict, authentication_token: str) -> bytes:
    bg_r = pass_data.get("bg_red", 0.0)
    bg_g = pass_data.get("bg_green", 0.0)
    bg_b = pass_data.get("bg_blue", 0.0)
    fg_r = pass_data.get("fg_red", 1.0)
    fg_g = pass_data.get("fg_green", 1.0)
    fg_b = pass_data.get("fg_blue", 1.0)
    lb_r = pass_data.get("lb_red", fg_r)
    lb_g = pass_data.get("lb_green", fg_g)
    lb_b = pass_data.get("lb_blue", fg_b)

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
    language = pass_data.get("language", "en")
    icon_image: bytes | None = pass_data.get("icon_image")

    expired = _is_expired(pass_data)
    uses_left = max(0, max_use - use_count)

    # Build coupon pass info
    coupon = Coupon()
    coupon.addHeaderField("discount", discount, _t(language, "label_discount"))
    coupon.addPrimaryField("title", title, _t(language, "label_coupon"))

    usage_field = Field("usage", f"{use_count}/{max_use}", _t(language, "label_uses"))
    if expired:
        status_field = Field("status", _t(language, "value_expired"), _t(language, "label_status"))
    else:
        status_field = Field("status", str(uses_left) + _t(language, "change_message_left"), _t(language, "label_status"))
        status_field.changeMessage = _t(language, "change_message").format(title=title)
    expiry_field = Field("expiry", _t(language, "value_no_expiry") if not expiration_date else expiration_date.split("T")[0], _t(language, "label_expire_date"))

    empty_field = Field("empty", "", "")  # Spacer to push status to the right
    coupon.secondaryFields.append(usage_field)
    coupon.secondaryFields.append(status_field)
    coupon.secondaryFields.append(empty_field)
    coupon.secondaryFields.append(expiry_field)

    coupon.addBackField("desc", description, _t(language, "label_description"))
    coupon.addBackField("maxUses", str(max_use), _t(language, "label_max_uses"))
    coupon.addBackField("currentUses", str(use_count), _t(language, "label_current_uses"))
    coupon.addBackField(
        "keepAfterUse",
        _t(language, "value_yes") if keep_after_used_up else _t(language, "value_no"),
        _t(language, "label_keep_after_use"),
    )

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
    passfile.labelColor = _rgb_string(lb_r, lb_g, lb_b)
    passfile.authenticationToken = authentication_token
    passfile.webServiceURL = WEB_SERVICE_URL.rstrip("/") + "/"

    if expiration_date:
        passfile.expirationDate = expiration_date

    if expired:
        passfile.voided = True  # type: ignore[assignment]

    relevant_date = pass_data.get("relevant_date")
    if relevant_date:
        passfile.relevantDate = relevant_date

    locations = pass_data.get("locations")
    if locations:
        passfile.locations = locations

    ibeacons = pass_data.get("ibeacons")
    if ibeacons:
        passfile.ibeacons = ibeacons

    passfile.barcode = Barcode(message=coupon_id, format=BarcodeFormat.QR)

    # Add images — use provided icon if available, else solid-color placeholder
    if icon_image:
        for name, size in [
            ("logo.png", 50), ("logo@2x.png", 100), ("logo@3x.png", 150),
        ]:
            passfile.addFile(name, io.BytesIO(_resize_png(icon_image, size, size)))
    else:
        for name, size in [
            ("logo.png", 50), ("logo@2x.png", 100), ("logo@3x.png", 150),
        ]:
            passfile.addFile(name, io.BytesIO(_solid_png(size, size, bg_r, bg_g, bg_b)))

    if icon_image:
        for name, size in [
            ("icon.png", 29), ("icon@2x.png", 58), ("icon@3x.png", 87),
        ]:
            passfile.addFile(name, io.BytesIO(_resize_png(icon_image, size, size)))
    else:
        for name, size in [
            ("icon.png", 29), ("icon@2x.png", 58), ("icon@3x.png", 87),
        ]:
            passfile.addFile(name, io.BytesIO(_solid_png(size, size, bg_r, bg_g, bg_b)))

    # Sign and return bytes
    zip_buf = io.BytesIO()
    passfile.create(_cert_pem_path, _key_pem_path, _wwdr_pem_path, _key_password, zip_buf)
    return zip_buf.getvalue()
