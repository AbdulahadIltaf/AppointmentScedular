import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, WebSocket, status, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.schemas import TriggerCallRequest, CallLogResponse
from app.services import db_service
from app.services.voice_service import voice_service
from app.services.call_orchestrator import CallOrchestrator, broadcaster

logger = logging.getLogger("app.calls_router")

router = APIRouter(prefix="/api/calls", tags=["calls"])

@router.get("/logs", response_model=List[CallLogResponse])
def get_call_logs(db: Session = Depends(get_db)):
    return db_service.get_all_call_logs(db)

@router.post("/trigger")
async def trigger_call(payload: TriggerCallRequest, db: Session = Depends(get_db)):
    """Triggers an outbound call for the specified appointment."""
    appointment = db_service.get_appointment(db, payload.appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment with ID {payload.appointment_id} not found"
        )
        
    if appointment.status in ["CONFIRMED", "CANCELLED"]:
         logger.warning(f"Appointment {payload.appointment_id} is already in state {appointment.status}.")
    
    try:
        # Trigger outbound call via Twilio
        call_sid = voice_service.make_outbound_call(
            appointment_id=appointment.id,
            phone_number=appointment.phone_number
        )
        
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
        logger.error(f"Failed to trigger call: {e}")
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
    # Dynamically determine the WebSocket URL based on request URL
    # Replace http/https with ws/wss
    scheme = "wss" if request.url.scheme == "https" else "ws"
    netloc = request.url.netloc
    
    # Construct the WebSocket URL for Twilio to send media stream to
    websocket_url = f"{scheme}://{netloc}/api/calls/stream?appointment_id={appointment_id}"
    
    logger.info(f"Returning TwiML. WebSocket Stream Target: {websocket_url}")
    
    twiml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Amy">Connecting you to Apex Dental reception...</Say>
    <Connect>
        <Stream url="{websocket_url}" />
    </Connect>
</Response>
"""
    return Response(content=twiml_content, media_type="application/xml")

@router.websocket("/stream")
async def handle_call_stream(websocket: WebSocket, appointment_id: int, db: Session = Depends(get_db)):
    """Handles the WebSocket media stream connection from Twilio."""
    await websocket.accept()
    logger.info(f"Twilio Media Stream WebSocket accepted for appointment {appointment_id}.")
    
    orchestrator = CallOrchestrator(websocket, appointment_id, db)
    try:
        await orchestrator.run()
    except Exception as e:
        logger.error(f"Error in Twilio Media Stream: {e}")
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
                    break
                
                # Retrieve and yield message from queue
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
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
