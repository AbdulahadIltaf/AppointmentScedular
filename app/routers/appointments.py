from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.schemas import AppointmentCreate, AppointmentResponse
from app.services import db_service

router = APIRouter(prefix="/api/appointments", tags=["appointments"])

@router.get("/", response_model=List[AppointmentResponse])
def get_appointments(db: Session = Depends(get_db)):
    return db_service.get_appointments(db)

@router.get("/slots")
def get_available_slots():
    """Returns available slots for rescheduling."""
    return db_service.get_available_slots_spoken()

@router.post("/", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def create_appointment(appointment: AppointmentCreate, db: Session = Depends(get_db)):
    return db_service.create_appointment(
        db,
        patient_name=appointment.patient_name,
        phone_number=appointment.phone_number,
        appointment_time=appointment.appointment_time,
        notes=appointment.notes
    )

@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(appointment_id: int, db: Session = Depends(get_db)):
    db_appointment = db_service.get_appointment(db, appointment_id)
    if not db_appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment with ID {appointment_id} not found"
        )
    return db_appointment
