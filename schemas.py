from typing import Literal, Optional

from pydantic import BaseModel


class ColorComponent(BaseModel):
    red: float
    green: float
    blue: float


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