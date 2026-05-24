import asyncio
import logging
from urllib.parse import parse_qs
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, WebSocket, status, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect
from typing import List

from app.config import settings
from app.database import get_db, SessionLocal
from app.schemas import TriggerCallRequest, CallLogResponse
from app.services import db_service
from app.services.voice_service import voice_service
from app.services.call_orchestrator import CallOrchestrator, broadcaster

logger = logging.getLogger("app.calls_router")

router = APIRouter(prefix="/api/calls", tags=["calls"])

_retry_state_by_appointment: dict[int, dict] = {}


def _get_retry_delays() -> list[int]:
    return [
        int(part.strip())
        for part in settings.OUTBOUND_RETRY_DELAYS_SECONDS.split(",")
        if part.strip()
    ]


def _get_retry_statuses() -> set[str]:
    return {
        part.strip().lower()
        for part in settings.OUTBOUND_RETRY_ON_STATUSES.split(",")
        if part.strip()
    }


def _reset_retry_state(appointment_id: int):
    state = _retry_state_by_appointment.get(appointment_id)
    if state and state.get("task") and not state["task"].done():
        state["task"].cancel()
    _retry_state_by_appointment[appointment_id] = {
        "attempt_index": 0,
        "active_call_sid": None,
        "completed": False,
        "task": None,
    }


async def _retry_outbound_call(appointment_id: int, delay_seconds: int, next_attempt_index: int):
    try:
        logger.info(
            "Scheduling outbound retry: appointment_id=%s next_attempt=%s delay_seconds=%s",
            appointment_id,
            next_attempt_index + 1,
            delay_seconds,
        )
        await broadcaster.broadcast("call_state", {
            "appointment_id": appointment_id,
            "status": "retrying",
            "retry_attempt": next_attempt_index + 1,
            "retry_delay_seconds": delay_seconds,
        })
        await broadcaster.broadcast(
            "status",
            {"text": f"Call was busy. Retrying in {delay_seconds} seconds..."}
        )
        await asyncio.sleep(delay_seconds)

        state = _retry_state_by_appointment.get(appointment_id)
        if not state or state.get("completed"):
            logger.info("Skipping retry because appointment is already completed: appointment_id=%s", appointment_id)
            return

        db = SessionLocal()
        try:
            appointment = db_service.get_appointment(db, appointment_id)
            if not appointment:
                logger.warning("Skipping retry because appointment was not found: appointment_id=%s", appointment_id)
                return

            logger.info(
                "Retrying outbound call: appointment_id=%s patient=%s phone=%s attempt=%s",
                appointment.id,
                appointment.patient_name,
                appointment.phone_number,
                next_attempt_index + 1,
            )
            call_sid = voice_service.make_outbound_call(
                appointment_id=appointment.id,
                phone_number=appointment.phone_number,
            )
            db_service.create_call_log(db, appointment.id, call_sid)

            state["active_call_sid"] = call_sid
            state["attempt_index"] = next_attempt_index
            state["task"] = None

            await broadcaster.broadcast("call_state", {
                "appointment_id": appointment.id,
                "twilio_call_sid": call_sid,
                "status": "ringing",
                "retry_attempt": next_attempt_index + 1,
            })
            await broadcaster.broadcast(
                "status",
                {"text": f"Retrying call to {appointment.patient_name}..."}
            )
        finally:
            db.close()
    except asyncio.CancelledError:
        logger.info("Cancelled outbound retry task: appointment_id=%s", appointment_id)
    except Exception:
        logger.exception("Retry attempt failed for appointment_id=%s", appointment_id)

@router.get("/logs", response_model=List[CallLogResponse])
def get_call_logs(db: Session = Depends(get_db)):
    return db_service.get_all_call_logs(db)

@router.post("/trigger")
async def trigger_call(payload: TriggerCallRequest, db: Session = Depends(get_db)):
    """Triggers an outbound call for the specified appointment."""
    logger.info("Trigger call request received: appointment_id=%s", payload.appointment_id)
    _reset_retry_state(payload.appointment_id)
    appointment = db_service.get_appointment(db, payload.appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment with ID {payload.appointment_id} not found"
        )
        
    if appointment.status in ["CONFIRMED", "CANCELLED"]:
         logger.warning(f"Appointment {payload.appointment_id} is already in state {appointment.status}.")
    
    try:
        logger.info(
            "Resolved appointment for outbound call: id=%s patient=%s phone=%s status=%s time=%s",
            appointment.id,
            appointment.patient_name,
            appointment.phone_number,
            appointment.status,
            appointment.appointment_time,
        )
        # Trigger outbound call via Twilio
        call_sid = voice_service.make_outbound_call(
            appointment_id=appointment.id,
            phone_number=appointment.phone_number
        )
        _retry_state_by_appointment[appointment.id]["active_call_sid"] = call_sid
        
        # Log the initiation state
        db_service.create_call_log(db, appointment.id, call_sid)
        
        # Broadcast dialing state to UI
        await broadcaster.broadcast("call_state", {
            "appointment_id": appointment.id,
            "twilio_call_sid": call_sid,
            "status": "ringing"
        })
        await broadcaster.broadcast("status", {"text": f"Dialing {appointment.patient_name}..."})
        
        return {
            "success": True,
            "message": f"Outbound call initiated successfully to {appointment.patient_name}.",
            "call_sid": call_sid
        }
    except Exception as e:
        logger.exception("Failed to trigger call for appointment_id=%s", payload.appointment_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate call: {str(e)}"
        )

@router.post("/twiml")
@router.get("/twiml")
async def get_twiml(request: Request, appointment_id: int):
    """
    Twilio calls this webhook when the call is answered.
    We return TwiML connecting the call to our WebSocket media stream.
    """
    # Prefer the configured public base URL because reverse proxies/tunnels
    # often reach the app over local HTTP even when Twilio is calling HTTPS.
    public_base_url = settings.BASE_URL.rstrip("/")
    parsed_base_url = urlparse(public_base_url)

    if parsed_base_url.scheme and parsed_base_url.netloc:
        scheme = "wss" if parsed_base_url.scheme == "https" else "ws"
        netloc = parsed_base_url.netloc
    else:
        scheme = "wss" if request.url.scheme == "https" else "ws"
        netloc = request.url.netloc
        logger.warning(
            "BASE_URL is not a valid absolute URL. Falling back to request host for Twilio stream URL."
        )

    # Construct the WebSocket URL for Twilio to send media stream to.
    websocket_url = f"{scheme}://{netloc}/api/calls/stream/{appointment_id}"
    
    logger.info(
        "Returning TwiML: appointment_id=%s request_scheme=%s request_host=%s websocket_target=%s user_agent=%s",
        appointment_id,
        request.url.scheme,
        request.url.netloc,
        websocket_url,
        request.headers.get("user-agent"),
    )
    
    twiml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Amy">Connecting you to Apex Dental reception...</Say>
    <Connect>
        <Stream url="{websocket_url}" />
    </Connect>
</Response>
"""
    return Response(content=twiml_content, media_type="application/xml")

@router.post("/status")
async def handle_call_status(request: Request, db: Session = Depends(get_db)):
    """Receives Twilio call progress callbacks for outbound call diagnosis."""
    body = await request.body()
    form = parse_qs(body.decode("utf-8"))
    appointment_id_raw = request.query_params.get("appointment_id")
    appointment_id = int(appointment_id_raw) if appointment_id_raw and appointment_id_raw.isdigit() else None
    call_sid = form.get("CallSid", [None])[0]
    call_status = form.get("CallStatus", [None])[0]
    answered_by = form.get("AnsweredBy", [None])[0]
    to_number = form.get("To", [None])[0]
    from_number = form.get("From", [None])[0]
    direction = form.get("Direction", [None])[0]

    logger.info(
        "Twilio status callback: sid=%s status=%s to=%s from=%s answered_by=%s direction=%s raw=%s",
        call_sid,
        call_status,
        to_number,
        from_number,
        answered_by,
        direction,
        {k: v[0] if len(v) == 1 else v for k, v in form.items()},
    )

    if call_sid and call_status:
        db_service.update_call_log(db, call_sid, call_status)

    if appointment_id is not None:
        state = _retry_state_by_appointment.setdefault(appointment_id, {
            "attempt_index": 0,
            "active_call_sid": call_sid,
            "completed": False,
            "task": None,
        })
        if call_sid:
            state["active_call_sid"] = call_sid

        normalized_status = (call_status or "").lower()
        retry_statuses = _get_retry_statuses()
        retry_delays = _get_retry_delays()

        if normalized_status in {"in-progress", "answered", "completed"}:
            state["completed"] = normalized_status in {"in-progress", "answered", "completed"}
            if state.get("task") and not state["task"].done():
                state["task"].cancel()
                state["task"] = None
            await broadcaster.broadcast("call_state", {
                "appointment_id": appointment_id,
                "twilio_call_sid": call_sid,
                "status": normalized_status,
            })

        elif normalized_status in retry_statuses:
            current_attempt_index = state.get("attempt_index", 0)
            if current_attempt_index < len(retry_delays) and not state.get("completed"):
                if not state.get("task") or state["task"].done():
                    delay_seconds = retry_delays[current_attempt_index]
                    state["task"] = asyncio.create_task(
                        _retry_outbound_call(appointment_id, delay_seconds, current_attempt_index + 1)
                    )
                await broadcaster.broadcast("call_state", {
                    "appointment_id": appointment_id,
                    "twilio_call_sid": call_sid,
                    "status": normalized_status,
                    "retry_attempt": current_attempt_index + 1,
                    "retry_delay_seconds": retry_delays[current_attempt_index],
                })
            else:
                await broadcaster.broadcast("call_state", {
                    "appointment_id": appointment_id,
                    "twilio_call_sid": call_sid,
                    "status": normalized_status,
                    "retry_exhausted": True,
                })
                await broadcaster.broadcast(
                    "status",
                    {"text": "Call could not connect after retry attempts."}
                )

    return {"success": True}

@router.websocket("/stream/{appointment_id}")
async def handle_call_stream(websocket: WebSocket, appointment_id: int, db: Session = Depends(get_db)):
    """Handles the WebSocket media stream connection from Twilio."""
    logger.info(
        "Incoming Twilio media stream websocket: appointment_id=%s client=%s query=%s headers_origin=%s headers_user_agent=%s",
        appointment_id,
        websocket.client,
        websocket.query_params,
        websocket.headers.get("origin"),
        websocket.headers.get("user-agent"),
    )
    await websocket.accept()
    logger.info(f"Twilio Media Stream WebSocket accepted for appointment {appointment_id}.")
    
    orchestrator = CallOrchestrator(websocket, appointment_id, db)
    try:
        await orchestrator.run()
    except Exception as e:
        logger.exception("Error in Twilio Media Stream for appointment_id=%s", appointment_id)
    finally:
        logger.info(f"Twilio Media Stream WebSocket closed for appointment {appointment_id}.")

@router.get("/events")
async def get_sse_events(request: Request):
    """SSE endpoint for broadcasting real-time call logs and status updates to UI."""
    async def event_generator():
        # Queue for this SSE client connection
        queue = asyncio.Queue()
        broadcaster.subscribe(queue)
        
        try:
            while True:
                # Disconnect if client leaves
                if await request.is_disconnected():
                    logger.info("SSE client disconnected before next send.")
                    break
                
                # Retrieve and yield message from queue
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield ": ping\n\n"
                except ClientDisconnect:
                    logger.info("SSE client disconnected during event send.")
                    break
        except asyncio.CancelledError:
            logger.info("SSE event stream cancelled by client.")
        except ClientDisconnect:
            logger.info("SSE client disconnected.")
        finally:
            broadcaster.unsubscribe(queue)
            
    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
