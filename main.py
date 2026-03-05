from fastapi import FastAPI

app = FastAPI(
    title="Wallet Coupon Creator Server",
    description="A server to create and manage Apple Wallet coupons, including device registration for push notifications",
    version="1.0.0",
    root_path="/api"
)

@app.get("/health")
async def health_check():
    return {"status": "ok"}