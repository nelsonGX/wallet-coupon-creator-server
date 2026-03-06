# Lock Screen Fields — relevantDate, locations, iBeacons

These three optional fields tell Apple Wallet **when and where** to surface the pass on the lock screen without the user opening the app.

---

## Fields Overview

| Field | Apple Wallet key | Effect |
|---|---|---|
| `relevantDate` | `relevantDate` | Show pass at a specific date/time |
| `locations` | `locations` | Show pass when near a GPS coordinate |
| `ibeacons` | `beacons` | Show pass when near a Bluetooth iBeacon |

All three are **optional**. Omit any you don't need.

---

## API Usage

Both `POST /sign-pass` and `POST /update-pass` accept these fields inside the `data` JSON form field alongside the existing pass properties.

### Request shape (multipart/form-data)

```
POST /sign-pass
Content-Type: multipart/form-data

data = <JSON string — see below>
icon = <optional image file>
```

### Full JSON schema

```json
{
  "couponID": "string (required)",
  "title": "string (required)",
  "backgroundColor": { "red": 0.0, "green": 0.0, "blue": 0.0 },
  "foregroundColor": { "red": 1.0, "green": 1.0, "blue": 1.0 },

  "relevantDate": "2025-12-31T18:00:00+08:00",

  "locations": [
    {
      "latitude": 25.0478,
      "longitude": 121.5319,
      "altitude": 10.0,
      "relevantText": "Welcome to our store!"
    }
  ],

  "ibeacons": [
    {
      "proximityUUID": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
      "major": 1,
      "minor": 2,
      "relevantText": "You're near the checkout counter"
    }
  ]
}
```

---

## Field Details

### `relevantDate`

- **Type:** `string` — ISO 8601 datetime with timezone offset
- **Effect:** Pass appears on lock screen at this exact moment
- **Format:** `"YYYY-MM-DDTHH:MM:SS±HH:MM"`

```json
"relevantDate": "2025-12-31T18:00:00+08:00"
```

> Use the local timezone of the event, not UTC, so the pass appears at the right local time regardless of where the user is.

---

### `locations`

- **Type:** array of location objects
- **Effect:** Pass surfaces on lock screen when the device enters the vicinity of any listed coordinate (Apple uses ~100 m radius)
- **Limit:** Up to **10** locations per pass (Apple Wallet limit)

| Property | Type | Required | Description |
|---|---|---|---|
| `latitude` | `float` | yes | Decimal degrees, e.g. `25.0478` |
| `longitude` | `float` | yes | Decimal degrees, e.g. `121.5319` |
| `altitude` | `float` | no | Meters above sea level |
| `relevantText` | `string` | no | Text shown on lock screen when near this location |

```json
"locations": [
  {
    "latitude": 25.0478,
    "longitude": 121.5319,
    "relevantText": "Show this coupon at the cashier"
  }
]
```

---

### `ibeacons`

- **Type:** array of iBeacon objects
- **Effect:** Pass surfaces on lock screen when the device detects a matching iBeacon
- **Limit:** Up to **10** beacons per pass (Apple Wallet limit)

| Property | Type | Required | Description |
|---|---|---|---|
| `proximityUUID` | `string` | yes | UUID of the beacon (uppercase, standard format) |
| `major` | `int` | no | Major value (0–65535) to narrow the beacon |
| `minor` | `int` | no | Minor value (0–65535) to narrow further |
| `relevantText` | `string` | no | Text shown on lock screen when beacon is detected |

```json
"ibeacons": [
  {
    "proximityUUID": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
    "major": 1,
    "minor": 5,
    "relevantText": "You're near the VIP counter"
  }
]
```

> `major` and `minor` are optional — omitting them matches **any** beacon with the given UUID.

---

## Complete Example

```swift
// Swift client example
let passData: [String: Any] = [
    "couponID": "COUPON-001",
    "title": "10% Off",
    "discount": "10%",
    "organizationName": "My Shop",
    "backgroundColor": ["red": 0.1, "green": 0.4, "blue": 0.8],
    "foregroundColor": ["red": 1.0, "green": 1.0, "blue": 1.0],

    // Show on lock screen at event time
    "relevantDate": "2025-12-31T18:00:00+08:00",

    // Show when near the store
    "locations": [
        [
            "latitude": 25.0478,
            "longitude": 121.5319,
            "relevantText": "Show this coupon at our store"
        ]
    ],

    // Show when near in-store beacon
    "ibeacons": [
        [
            "proximityUUID": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
            "major": 1,
            "minor": 1,
            "relevantText": "You're near the checkout"
        ]
    ]
]

var request = URLRequest(url: URL(string: "https://your-server.com/api/sign-pass")!)
request.httpMethod = "POST"
let boundary = UUID().uuidString
request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

var body = Data()
// Append JSON data part
let jsonData = try! JSONSerialization.data(withJSONObject: passData)
body.append("--\(boundary)\r\n".data(using: .utf8)!)
body.append("Content-Disposition: form-data; name=\"data\"\r\n\r\n".data(using: .utf8)!)
body.append(jsonData)
body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
request.httpBody = body
```

```kotlin
// Kotlin/Android client example (OkHttp)
val passJson = JSONObject().apply {
    put("couponID", "COUPON-001")
    put("title", "10% Off")
    put("backgroundColor", JSONObject().apply {
        put("red", 0.1); put("green", 0.4); put("blue", 0.8)
    })
    put("foregroundColor", JSONObject().apply {
        put("red", 1.0); put("green", 1.0); put("blue", 1.0)
    })
    put("relevantDate", "2025-12-31T18:00:00+08:00")
    put("locations", JSONArray().apply {
        put(JSONObject().apply {
            put("latitude", 25.0478)
            put("longitude", 121.5319)
            put("relevantText", "Show this coupon at our store")
        })
    })
    put("ibeacons", JSONArray().apply {
        put(JSONObject().apply {
            put("proximityUUID", "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0")
            put("major", 1)
            put("minor", 1)
            put("relevantText", "You're near the checkout")
        })
    })
}

val requestBody = MultipartBody.Builder()
    .setType(MultipartBody.FORM)
    .addFormDataPart("data", passJson.toString())
    .build()
```

---

## Notes

- All three fields are **independently optional** — use any combination.
- Removing a field (sending `null` or omitting it) clears it from the stored pass on the next `update-pass` call.
- `ibeacons` requires the device to have Bluetooth enabled and the app to have location permissions.
- Apple Wallet enforces a **combined maximum of 10** locations + beacons per pass.
