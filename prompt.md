# Build an Apple Wallet `.pkpass` Signing & Update Server

## Overview

Build an HTTP server that:
1. Accepts coupon data as JSON, constructs a valid Apple Wallet `.pkpass` bundle (coupon style), signs it, and returns the `.pkpass` file
2. Implements Apple's Web Service protocol so passes auto-update on all devices when coupon data changes (usage count, recharge, edits)
3. Sends push notifications via APNs to trigger Wallet to pull updated passes

## Configuration

- **Pass Type Identifier:** `pass.com.nelsongx.apps.coupon-creator`
- **Team Identifier:** `G4LXL97NF9`
- **Organization Name:** Provided in request, or default to `"Coupon Creator"`

Environment variables:

| Variable | Description |
|---|---|
| `PASS_CERTIFICATE_PATH` | Path to `.p12` certificate file |
| `PASS_CERTIFICATE_PASSWORD` | Password for the `.p12` file |
| `WWDR_CERTIFICATE_PATH` | Path to Apple WWDR G4 intermediate cert |
| `PORT` | Server port (default 8000) |
| `DATABASE_URL` | Database connection string (SQLite for local, PostgreSQL for production) |

## Tech Stack

- Python FastAPI
- **Database:** SQLite for development, PostgreSQL for production (needs persistent storage for device registrations)
- OpenSSL for signing
- HTTP/2 client for APNs push notifications

---

## Part 1: Pass Creation API (called by the iOS app)

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

**Server behavior:**
1. Save/update the coupon data in the `passes` database table (upsert by `couponID`)
2. Set `lastUpdated` to current timestamp
3. Build and sign the `.pkpass` bundle (see "How to Build the `.pkpass` Bundle" below)
4. Return the `.pkpass` as binary with `Content-Type: application/vnd.apple.pkpass`

### `POST /update-pass`

Same request body as `/sign-pass`. Used when the iOS app updates a coupon (redeem, recharge, edit).

**Server behavior:**
1. Update the coupon data in the `passes` table
2. Set `lastUpdated` to current timestamp
3. Build and sign a new `.pkpass` bundle
4. **Send push notifications** to all devices registered for this pass (see Part 3)
5. Return the new `.pkpass` as binary

---

## Part 2: Apple Wallet Web Service Endpoints

These endpoints are called **by Apple Wallet on the user's device**, not by the iOS app. They follow Apple's required Web Service protocol exactly.

The base URL for these is your server's public URL (e.g. `https://your-server.com/api`). This URL goes into `pass.json` as `webServiceURL`.

### 2.1 Register a Device for Pass Updates

```
POST /api/v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}/{serialNumber}
```

**Headers:**
- `Authorization: ApplePass <authenticationToken>`

**Request body:**
```json
{
  "pushToken": "<APNs push token>"
}
```

**Server behavior:**
1. Validate the `authenticationToken` matches the pass's stored token
2. Create/update the device in the `devices` table (store `deviceLibraryIdentifier` and `pushToken`)
3. Create an entry in the `registrations` table linking the device to the pass
4. Return `201 Created` if new registration, `200 OK` if already registered

### 2.2 Get Serial Numbers for Updated Passes

```
GET /api/v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}?passesUpdatedSince={previousLastUpdated}
```

**Server behavior:**
1. Look up all passes registered to this device
2. If `passesUpdatedSince` is provided, filter to passes updated after that timestamp
3. Return `200` with body:

```json
{
  "serialNumbers": ["550e8400-e29b-41d4-a716-446655440000", "..."],
  "lastUpdated": "1709654400"
}
```

4. Return `204 No Content` if no passes have been updated

### 2.3 Get the Latest Version of a Pass

```
GET /api/v1/passes/{passTypeIdentifier}/{serialNumber}
```

**Headers:**
- `Authorization: ApplePass <authenticationToken>`

**Server behavior:**
1. Validate the `authenticationToken`
2. Look up the pass data from the `passes` table by `serialNumber`
3. Build and sign a fresh `.pkpass` bundle from the stored data
4. Return the `.pkpass` with `Content-Type: application/vnd.apple.pkpass`
5. Return `304 Not Modified` if the pass hasn't changed (compare `If-Modified-Since` header with `lastUpdated`)

### 2.4 Unregister a Device

```
DELETE /api/v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}/{serialNumber}
```

**Headers:**
- `Authorization: ApplePass <authenticationToken>`

**Server behavior:**
1. Validate the `authenticationToken`
2. Delete the registration linking this device to this pass
3. If the device has no more registrations, delete the device entry
4. Return `200 OK`

### 2.5 Log Errors (optional but recommended)

```
POST /api/v1/log
```

**Request body:**
```json
{
  "logs": ["error message 1", "error message 2"]
}
```

**Server behavior:**
1. Log the messages to your server logs for debugging
2. Return `200 OK`

---

## Part 3: Push Notifications via APNs

When a pass is updated (via `/update-pass`), send push notifications to all registered devices to tell Wallet to fetch the new pass.

**How it works:**
1. Look up all devices registered for the updated pass in the `registrations` table
2. For each device, send a push notification to APNs using:
   - **Certificate:** The same Pass Type ID certificate (`.p12`) used for signing
   - **Push token:** From the `devices` table
   - **Payload:** An empty JSON object `{}`
   - **Topic:** `pass.com.nelsongx.apps.coupon-creator` (the pass type identifier)
   - **APNs endpoint:** `https://api.push.apple.com/3/device/{pushToken}` (production)
3. If APNs returns an error that the push token is invalid, delete that device from the database

**Important:** Pass update push notifications only work in the **production** APNs environment, not sandbox. Use `api.push.apple.com`, not `api.sandbox.push.apple.com`.

---

## Database Schema

### `passes` table

| Column | Type | Description |
|---|---|---|
| `serial_number` | TEXT PRIMARY KEY | The couponID (UUID string) |
| `authentication_token` | TEXT | Random token generated when pass is created |
| `title` | TEXT | Coupon title |
| `description` | TEXT | Coupon description |
| `discount` | TEXT | Discount text |
| `organization_name` | TEXT | Organization name |
| `use_count` | INTEGER | Current usage count |
| `max_use` | INTEGER | Maximum uses allowed |
| `is_rechargeable` | BOOLEAN | Whether the coupon can be recharged |
| `keep_after_used_up` | BOOLEAN | Keep pass in Wallet after fully used |
| `expiration_date` | TEXT | ISO 8601 date or NULL |
| `bg_red` | REAL | Background color red (0.0-1.0) |
| `bg_green` | REAL | Background color green |
| `bg_blue` | REAL | Background color blue |
| `fg_red` | REAL | Foreground color red |
| `fg_green` | REAL | Foreground color green |
| `fg_blue` | REAL | Foreground color blue |
| `last_updated` | INTEGER | Unix timestamp of last update |
| `created_at` | TEXT | ISO 8601 creation date |

### `devices` table

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | Auto-increment ID |
| `device_library_identifier` | TEXT UNIQUE | Identifier sent by the device |
| `push_token` | TEXT | APNs push token for this device |

### `registrations` table

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | Auto-increment ID |
| `device_id` | INTEGER | Foreign key to devices table |
| `serial_number` | TEXT | Foreign key to passes table |
| UNIQUE | | `(device_id, serial_number)` |

---

## How to Build the `.pkpass` Bundle

A `.pkpass` file is a ZIP archive containing these files:

### 1. `pass.json`

```json
{
  "formatVersion": 1,
  "passTypeIdentifier": "pass.com.nelsongx.apps.coupon-creator",
  "teamIdentifier": "G4LXL97NF9",
  "serialNumber": "<couponID>",
  "authenticationToken": "<random 16+ character hex string, stored in DB>",
  "webServiceURL": "https://<YOUR_SERVER_URL>/api",
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
        "value": "<useCount>/<maxUse>",
        "changeMessage": "Usage updated to %@"
      },
      {
        "key": "status",
        "label": "STATUS",
        "value": "<'Active' or 'Used Up' based on useCount vs maxUse>",
        "changeMessage": "Status changed to %@"
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

**Critical fields for updates:**
- `authenticationToken` — Generate a random hex string (at least 16 characters) when the pass is first created. Store it in the DB. **Never change it** during updates.
- `webServiceURL` — Your server's public HTTPS URL followed by `/api`. This tells Wallet where to call for registration and updates.
- `changeMessage` on fields — When the field value changes, Wallet shows this message on the lock screen. `%@` is replaced with the new value.

**Other important notes on `pass.json`:**
- `foregroundColor` and `backgroundColor` must be CSS-style strings: `"rgb(51, 127, 229)"`
- Convert the 0.0-1.0 float values to 0-255 integers: `Math.round(value * 255)`
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

If using the `.p12` directly, first extract the cert and key at server startup:

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

---

## Project Structure

```
wallet-pass-server/
├── main.py
... (routes and lib)
├── certs/
│   ├── pass.p12          (user provides)
│   └── wwdr.pem          (Apple WWDR G4 cert)
├── .env.example
...
```

## Health Check

### `GET /health`

Returns `{ "status": "ok" }` so the iOS app can verify connectivity.

## Deployment Notes

- Listen on `PORT` env var (default 8000)
- Enable CORS for the iOS app
- **Must use HTTPS in production** (required by Apple for `webServiceURL`)
- The `webServiceURL` in `pass.json` must be set to your deployed server's public URL + `/api`
- Store the `WEB_SERVICE_URL` as an environment variable so it can be configured per deployment

## Testing

Include a test script or curl command in the README:

```bash
# Create a pass
curl -X POST http://localhost:8000/sign-pass \
  -H "Content-Type: application/json" \
  -d '{"title":"Test Coupon","discount":"10% OFF","organizationName":"Test Shop","useCount":0,"maxUse":3,"isRechargeable":false,"keepAfterUsedUp":true,"couponID":"550e8400-e29b-41d4-a716-446655440000","backgroundColor":{"red":0.2,"green":0.5,"blue":0.9},"foregroundColor":{"red":1,"green":1,"blue":1}}' \
  -o test.pkpass

# Update a pass (redeem one use)
curl -X POST http://localhost:8000/update-pass \
  -H "Content-Type: application/json" \
  -d '{"title":"Test Coupon","discount":"10% OFF","organizationName":"Test Shop","useCount":1,"maxUse":3,"isRechargeable":false,"keepAfterUsedUp":true,"couponID":"550e8400-e29b-41d4-a716-446655440000","backgroundColor":{"red":0.2,"green":0.5,"blue":0.9},"foregroundColor":{"red":1,"green":1,"blue":1}}' \
  -o test-updated.pkpass
```

You can test the output by dragging `test.pkpass` onto the iOS Simulator — Wallet should show the "Add Pass" dialog if it's valid.
**Note:** Push notifications for pass updates only work in the production APNs environment. They will not work in the simulator or with sandbox APNs.

