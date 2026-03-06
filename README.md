# Wallet Coupon Creator Server

A Python FastAPI server that creates and signs Apple Wallet `.pkpass` coupon passes, implements Apple's Web Service protocol for automatic pass updates, and sends APNs push notifications.

## Requirements

- Python 3.10+
- OpenSSL
- Apple Pass Type ID certificate (`.p12`)

## Setup

1. **Install dependencies**

   ```bash
   uv sync     # install uv if you don't have it: pip install uv
   ```

2. **Place certificates**

   ```
   certs/
   ├── pass.p12      # Your Pass Type ID certificate
   └── wwdr.pem      # Apple WWDR G4 cert (already included in this repo, but you can update it if needed)
   ```

   Download the Apple WWDR G4 certificate from [Apple PKI](https://www.apple.com/certificateauthority/).

3. **Configure environment**

   ```bash
   cp .env.example .env
   ```

   Edit `.env`:

   | Variable | Description |
   |---|---|
   | `PASS_CERTIFICATE_PATH` | Path to `.p12` certificate |
   | `PASS_CERTIFICATE_PASSWORD` | Password for the `.p12` file |
   | `WWDR_CERTIFICATE_PATH` | Path to WWDR `.pem` cert |
   | `PORT` | Server port (default: `8000`) |
   | `DATABASE_URL` | SQLite (`sqlite:///./wallet.db`) or PostgreSQL URL |
   | `WEB_SERVICE_URL` | Public HTTPS URL + `/api` (e.g. `https://your-server.com/api`) |

4. **Run the server**

   ```bash
   uv run fastapi dev    # development mode with auto-reload
    # or
   uv run fastapi run    # production mode
   ```

## API

### `POST /sign-pass`

Creates a new coupon pass. Returns a `.pkpass` file.

### `POST /update-pass`

Updates an existing pass and sends push notifications to all registered devices.

### `GET /health`

Returns `{"status": "ok"}`.

### Apple Wallet Web Service (called by iOS Wallet app)

| Method | Endpoint |
|---|---|
| `POST` | `/api/v1/devices/{deviceId}/registrations/{passTypeId}/{serialNumber}` |
| `GET` | `/api/v1/devices/{deviceId}/registrations/{passTypeId}` |
| `GET` | `/api/v1/passes/{passTypeId}/{serialNumber}` |
| `DELETE` | `/api/v1/devices/{deviceId}/registrations/{passTypeId}/{serialNumber}` |
| `POST` | `/api/v1/log` |

## Testing

```bash
# Create a pass
curl -X POST http://localhost:8000/sign-pass \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Coupon",
    "discount": "10% OFF",
    "organizationName": "Test Shop",
    "useCount": 0,
    "maxUse": 3,
    "isRechargeable": false,
    "keepAfterUsedUp": true,
    "couponID": "550e8400-e29b-41d4-a716-446655440000",
    "backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.9},
    "foregroundColor": {"red": 1, "green": 1, "blue": 1}
  }' \
  -o test.pkpass

# Update a pass (redeem one use)
curl -X POST http://localhost:8000/update-pass \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Coupon",
    "discount": "10% OFF",
    "organizationName": "Test Shop",
    "useCount": 1,
    "maxUse": 3,
    "isRechargeable": false,
    "keepAfterUsedUp": true,
    "couponID": "550e8400-e29b-41d4-a716-446655440000",
    "backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.9},
    "foregroundColor": {"red": 1, "green": 1, "blue": 1}
  }' \
  -o test-updated.pkpass
```

Open `test.pkpass` on your Mac or send it to your iPhone to verify it opens in Wallet.

## Deployment

- **HTTPS is required** — Apple's `webServiceURL` must use HTTPS.
- Set `WEB_SERVICE_URL` to your public server URL (e.g. `https://your-server.com/api`).
- Use PostgreSQL in production (`DATABASE_URL=postgresql://...`).
- Push notifications use the **production** APNs endpoint (`api.push.apple.com`) — they do not work in the simulator.
