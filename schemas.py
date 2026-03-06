from typing import List, Literal, Optional

from pydantic import BaseModel


class ColorComponent(BaseModel):
    red: float
    green: float
    blue: float


class Location(BaseModel):
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    relevantText: Optional[str] = None


class IBeacon(BaseModel):
    proximityUUID: str
    major: Optional[int] = None
    minor: Optional[int] = None
    relevantText: Optional[str] = None


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
    labelColor: Optional[ColorComponent] = None
    language: Literal["en", "zh-TW"] = "en"
    relevantDate: Optional[str] = None
    locations: Optional[List[Location]] = None
    ibeacons: Optional[List[IBeacon]] = None