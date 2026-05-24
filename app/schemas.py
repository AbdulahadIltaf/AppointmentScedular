from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

# Appointment Schemas
class AppointmentBase(BaseModel):
    patient_name: str
    phone_number: str
    appointment_time: datetime
    notes: Optional[str] = None

class AppointmentCreate(AppointmentBase):
    pass

class AppointmentUpdate(BaseModel):
    status: Optional[str] = None
    cancellation_reason: Optional[str] = None
    appointment_time: Optional[datetime] = None

class AppointmentResponse(AppointmentBase):
    id: int
    status: str
    cancellation_reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# Call Log Schemas
class CallLogResponse(BaseModel):
    id: int
    twilio_call_sid: Optional[str] = None
    appointment_id: int
    status: str
    transcript: Optional[str] = None
    summary: Optional[str] = None
    duration: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True

# Request Schemas
class TriggerCallRequest(BaseModel):
    appointment_id: int
