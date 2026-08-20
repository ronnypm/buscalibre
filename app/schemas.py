"""Esquemas Pydantic para la API."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProductIn(BaseModel):
    url: str
    title: str | None = None
    author: str | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    source: str
    title: str | None
    author: str | None
    initial_price: float | None
    min_price: float | None
    min_price_at: datetime | None
    current_price: float | None
    last_scanned_at: datetime | None
    active: bool
    in_stock: bool
    created_at: datetime


class PricePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    price: float
    scanned_at: datetime


class ScanResult(BaseModel):
    scanned: int
    changed: int
    low_alert: int
    errors: int


class AlertOut(BaseModel):
    product_id: int
    title: str | None
    message: str
    kind: str  # up | down | low | setup