from pydantic import BaseModel, Field
from typing import Any


class Message(BaseModel):
    property_id: str
    guest_id: str
    message_id: str
    text: str


class Ask(BaseModel):
    property_id: str
    question: str


class PropertyConfig(BaseModel):
    property_id: str
    name: str
    city: str = ""
    total_rooms: int = 0
    language: str = "en"
    custom_faqs: list[dict] = Field(default_factory=list)


class MessageResponse(BaseModel):
    message_id: str
    intent: str | None
    confidence: float | None
    status: str
    note: str = ""


class AskResponse(BaseModel):
    answer: str | None
    sql: str | None = None
    rows: list[dict] = Field(default_factory=list)
    source: str | None = None
    type: str = "data"  # "data" | "rag" | "refused"


class EventRecord(BaseModel):
    id: int
    event_type: str
    payload: dict
    created_at: str


class BookingRecord(BaseModel):
    booking_id: str
    room_type: str
    checkin: str
    checkout: str
    status: str
    amount_inr: int
    source: str
    created_at: str | None = None
