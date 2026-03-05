# Build an Apple Wallet `.pkpass` Signing Server

## Overview

Build a lightweight HTTP server that accepts coupon data as JSON, constructs a valid Apple Wallet `.pkpass` bundle (coupon style), signs it with a Pass Type ID certificate, and returns the signed `.pkpass` file.

## Configuration

- **Pass Type Identifier:** `pass.com.nelsongx.apps.coupon-creator`
- **Team Identifier:** `G4LXL97NF9`
- **Organization Name:** Provided in request, or default to `"Coupon Creator"`
- The server should accept the `.p12` certificate file path and password via environment variables: `PASS_CERTIFICATE_PATH` and `PASS_CERTIFICATE_PASSWORD`
- Also needs the Apple WWDR (Worldwide Developer Relations) intermediate certificate. Download it from https://www.apple.com/certificateauthority/ (the "Worldwide Developer Relations - G4" certificate). Path via env var `WWDR_CERTIFICATE_PATH`.

## Tech Stack

- Python FastAPI
- Use OpenSSL for signing
- No database needed — stateless signing service

## API Endpoint

### `POST /sign-pass`

Request body (JSON):

```json
{
  "title": "20% Off Coffee",
  "description": "Valid at all locations",
  "discount": "20% OFF",
  "organizationName": "Coffee Shop",
  "useCount": 0,
  "maxUse": 5,
  "isRechargeable": false,
  "keepAfterUsedUp": true,
  "expirationDate": "2026-06-01T00:00:00Z",
  "couponID": "550e8400-e29b-41d4-a716-446655440000",
  "backgroundColor": { "red": 0.2, "green": 0.5, "blue": 0.9 },
  "foregroundColor": { "red": 1.0, "green": 1.0, "blue": 1.0 }
}
```

Response: The signed `.pkpass` file as binary data with `Content-Type: application/vnd.apple.pkpass`.

## How to Build the `.pkpass` Bundle

A `.pkpass` file is a ZIP archive containing these files:

### 1. `pass.json`

```json
{
  "formatVersion": 1,
  "passTypeIdentifier": "pass.com.nelsongx.apps.coupon-creator",
  "teamIdentifier": "G4LXL97NF9",
  "serialNumber": "<use the couponID from the request>",
  "organizationName": "<from request>",
  "description": "<title from request>",
  "logoText": "<organizationName from request>",
  "foregroundColor": "rgb(<r*255>, <g*255>, <b*255>)",
  "backgroundColor": "rgb(<r*255>, <g*255>, <b*255>)",
  "coupon": {
    "headerFields": [
      {
        "key": "discount",
        "label": "DISCOUNT",
        "value": "<discount from request>"
      }
    ],
    "primaryFields": [
      {
        "key": "title",
        "label": "COUPON",
        "value": "<title from request>"
      }
    ],
    "secondaryFields": [
      {
        "key": "usage",
        "label": "USES",
        "value": "<useCount>/<maxUse>"
      },
      {
        "key": "status",
        "label": "STATUS",
        "value": "<'Active' or 'Used Up' based on useCount vs maxUse>"
      }
    ],
    "auxiliaryFields": [
      {
        "key": "rechargeable",
        "label": "RECHARGEABLE",
        "value": "<'Yes' or 'No'>"
      }
    ],
    "backFields": [
      {
        "key": "desc",
        "label": "Description",
        "value": "<description from request>"
      },
      {
        "key": "maxUses",
        "label": "Maximum Uses",
        "value": "<maxUse>"
      },
      {
        "key": "currentUses",
        "label": "Current Uses",
        "value": "<useCount>"
      },
      {
        "key": "keepAfterUse",
        "label": "Keep After Used Up",
        "value": "<'Yes' or 'No'>"
      }
    ]
  },
  "barcodes": [
    {
      "format": "PKBarcodeFormatQR",
      "message": "<JSON string of the full request body>",
      "messageEncoding": "iso-8859-1"
    }
  ],
  "expirationDate": "<ISO 8601 date if provided, omit key if null>"
}
```

**Important notes on `pass.json`:**

- `foregroundColor` and `backgroundColor` must be CSS-style strings: `"rgb(51, 127, 229)"`
- Convert the 0.0–1.0 float values to 0–255 integers: `Math.round(value * 255)`
- `serialNumber` must be unique per pass — use the `couponID`
- If `expirationDate` is null/missing, omit the key entirely
- The `barcodes[0].message` should be the JSON-encoded request body so the iOS app can scan and decode it

### 2. Image files (generate simple placeholder images)

Required images (PNG format):

- `icon.png` (29x29) — small solid-color square
- `icon@2x.png` (58x58)
- `icon@3x.png` (87x87)
- `logo.png` (50x50) — can be same solid-color square
- `logo@2x.png` (100x100)
- `logo@3x.png` (150x150)

Generate these programmatically as solid-color PNGs using the background color from the request. Use any image library (e.g., `sharp` for Node.js, `Pillow` for Python).

### 3. `manifest.json`

A JSON dictionary mapping each file name to its SHA-1 hash:

```json
{
  "pass.json": "<sha1 hex of pass.json contents>",
  "icon.png": "<sha1 hex>",
  "icon@2x.png": "<sha1 hex>",
  "icon@3x.png": "<sha1 hex>",
  "logo.png": "<sha1 hex>",
  "logo@2x.png": "<sha1 hex>",
  "logo@3x.png": "<sha1 hex>"
}
```

### 4. `signature`

A PKCS #7 detached signature of `manifest.json`, created using:

- The Pass Type ID certificate + private key (from the `.p12` file)
- The Apple WWDR intermediate certificate

OpenSSL command equivalent:

```bash
openssl smime -sign -binary -in manifest.json \
  -out signature \
  -outform DER \
  -signer passCertificate.pem \
  -inkey passKey.pem \
  -certfile wwdr.pem \
  -passin pass:<password>
```

If using the `.p12` directly, first extract the cert and key:

```bash
# Extract certificate
openssl pkcs12 -in pass.p12 -clcerts -nokeys -out passCertificate.pem -passin pass:<password> -legacy
# Extract private key
openssl pkcs12 -in pass.p12 -nocerts -out passKey.pem -passin pass:<password> -legacy
```

### 5. ZIP everything into `.pkpass`

ZIP all files (`pass.json`, `manifest.json`, `signature`, and all image files) into a flat archive (no subdirectory). Return this as the response with:

- `Content-Type: application/vnd.apple.pkpass`
- `Content-Disposition: attachment; filename="coupon.pkpass"`

## Project Structure

```
wallet-pass-server/
├── main.py
├── certs/
│   ├── pass.p12          (user provides)
│   └── wwdr.pem          (Apple WWDR G4 cert)
├── .env.example
│   PASS_CERTIFICATE_PATH=./certs/pass.p12
│   PASS_CERTIFICATE_PASSWORD=
│   WWDR_CERTIFICATE_PATH=./certs/wwdr.pem
│   PORT=8324
└── README.md
```

## Health Check

### `GET /health`

Returns `{ "status": "ok" }` so the iOS app can verify connectivity.

## Deployment Notes

- Should be deployable to Railway, Render, Fly.io, or any Docker host
- Include a `Dockerfile` for easy deployment
- Listen on `PORT` env var (default 8324)
- Enable CORS for the iOS app
- No authentication needed initially (can be added later)

## Testing

Include a test script or curl command in the README:

```bash
curl -X POST http://localhost:8324/sign-pass \
  -H "Content-Type: application/json" \
  -d '{"title":"Test Coupon","discount":"10% OFF","organizationName":"Test Shop","useCount":0,"maxUse":3,"isRechargeable":false,"keepAfterUsedUp":true,"couponID":"550e8400-e29b-41d4-a716-446655440000","backgroundColor":{"red":0.2,"green":0.5,"blue":0.9},"foregroundColor":{"red":1,"green":1,"blue":1}}' \
  -o test.pkpass
```
