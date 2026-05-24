from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.models import Appointment, CallLog
from app.database import Base, engine

# Initialize Database tables
def init_db():
    Base.metadata.create_all(bind=engine)

# Helper to format datetime to a spoken friendly format
def format_datetime_spoken(dt: datetime) -> str:
    # Example: "Monday, May 25th at 10:00 AM"
    weekday = dt.strftime("%A")
    month = dt.strftime("%B")
    day = dt.day
    
    # Ordinal suffix (1st, 2nd, 3rd, 4th...)
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        
    time_str = dt.strftime("%I:%M %p").lstrip("0")  # e.g. "10:00 AM" or "2:30 PM"
    return f"{weekday}, {month} {day}{suffix} at {time_str}"

# Available slots for rescheduling
def get_available_slots() -> list[datetime]:
    # Generate 5 mock slots starting from next Monday
    slots = []
    today = datetime.now()
    # Find next Monday
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:  # Target is today or in the past of this week
        days_ahead += 7
    next_monday = today + timedelta(days=days_ahead)
    
    # 5 different slots
    slots.append(next_monday.replace(hour=9, minute=0, second=0, microsecond=0))      # Monday 9:00 AM
    slots.append(next_monday.replace(hour=14, minute=0, second=0, microsecond=0))     # Monday 2:00 PM
    slots.append((next_monday + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)) # Tuesday 11:00 AM
    slots.append((next_monday + timedelta(days=2)).replace(hour=10, minute=30, second=0, microsecond=0)) # Wednesday 10:30 AM
    slots.append((next_monday + timedelta(days=3)).replace(hour=15, minute=0, second=0, microsecond=0)) # Thursday 3:00 PM
    
    return slots

def get_available_slots_spoken() -> list[dict]:
    slots = get_available_slots()
    return [
        {
            "id": i + 1,
            "iso": slot.isoformat(),
            "spoken": format_datetime_spoken(slot)
        }
        for i, slot in enumerate(slots)
    ]

# Populate mock data if database is empty
def seed_mock_data(db: Session):
    if db.query(Appointment).count() == 0:
        now = datetime.now()
        # Mock appointment 1: John Doe, tomorrow at 10 AM
        tomorrow_10am = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        # Mock appointment 2: Jane Smith, in 2 days at 2:30 PM
        in_2_days_230pm = (now + timedelta(days=2)).replace(hour=14, minute=30, second=0, microsecond=0)
        # Mock appointment 3: Bob Johnson, in 3 days at 11:15 AM
        in_3_days_1115am = (now + timedelta(days=3)).replace(hour=11, minute=15, second=0, microsecond=0)
        
        appointments = [
            Appointment(
                patient_name="John Doe",
                phone_number="+15550199", # Placeholder
                appointment_time=tomorrow_10am,
                status="PENDING",
                notes="Routine dental cleaning with Dr. Sarah Smith"
            ),
            Appointment(
                patient_name="Jane Smith",
                phone_number="+15550200",
                appointment_time=in_2_days_230pm,
                status="PENDING",
                notes="Filling cavity repair with Dr. Sarah Smith"
            ),
            Appointment(
                patient_name="Bob Johnson",
                phone_number="+15550201",
                appointment_time=in_3_days_1115am,
                status="PENDING",
                notes="Consultation for dental implants with Dr. James Miller"
            )
        ]
        db.add_all(appointments)
        db.commit()

# CRUD operations
def get_appointments(db: Session):
    return db.query(Appointment).order_by(Appointment.appointment_time.asc()).all()

def get_appointment(db: Session, appointment_id: int):
    return db.query(Appointment).filter(Appointment.id == appointment_id).first()

def create_appointment(db: Session, patient_name: str, phone_number: str, appointment_time: datetime, notes: str = None):
    db_appointment = Appointment(
        patient_name=patient_name,
        phone_number=phone_number,
        appointment_time=appointment_time,
        status="PENDING",
        notes=notes
    )
    db.add(db_appointment)
    db.commit()
    db.refresh(db_appointment)
    return db_appointment

def update_appointment_status(db: Session, appointment_id: int, status: str, cancellation_reason: str = None):
    appointment = get_appointment(db, appointment_id)
    if appointment:
        appointment.status = status.upper()
        if cancellation_reason:
            appointment.cancellation_reason = cancellation_reason
        db.commit()
        db.refresh(appointment)
    return appointment

def reschedule_appointment(db: Session, appointment_id: int, new_time: datetime):
    appointment = get_appointment(db, appointment_id)
    if appointment:
        appointment.appointment_time = new_time
        appointment.status = "RESCHEDULED"
        db.commit()
        db.refresh(appointment)
    return appointment

# Call logs operations
def create_call_log(db: Session, appointment_id: int, twilio_call_sid: str = None):
    db_log = CallLog(
        appointment_id=appointment_id,
        twilio_call_sid=twilio_call_sid,
        status="queued"
    )
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log

def get_call_log_by_sid(db: Session, twilio_call_sid: str):
    return db.query(CallLog).filter(CallLog.twilio_call_sid == twilio_call_sid).first()

def update_call_log(db: Session, twilio_call_sid: str, status: str, transcript: str = None, summary: str = None, duration: int = None):
    log = get_call_log_by_sid(db, twilio_call_sid)
    if log:
        log.status = status
        if transcript is not None:
            log.transcript = transcript
        if summary is not None:
            log.summary = summary
        if duration is not None:
            log.duration = duration
        db.commit()
        db.refresh(log)
    return log

def get_all_call_logs(db: Session):
    return db.query(CallLog).order_by(CallLog.created_at.desc()).all()
