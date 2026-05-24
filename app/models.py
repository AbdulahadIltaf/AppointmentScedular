from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    appointment_time = Column(DateTime, nullable=False)
    status = Column(String, default="PENDING")  # PENDING, CONFIRMED, CANCELLED, RESCHEDULED
    cancellation_reason = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    calls = relationship("CallLog", back_populates="appointment")

class CallLog(Base):
    __tablename__ = "call_logs"

    id = Column(Integer, primary_key=True, index=True)
    twilio_call_sid = Column(String, unique=True, index=True, nullable=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=False)
    status = Column(String, default="queued")  # queued, ringing, in-progress, completed, failed
    transcript = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    duration = Column(Integer, nullable=True)  # in seconds
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    appointment = relationship("Appointment", back_populates="calls")
