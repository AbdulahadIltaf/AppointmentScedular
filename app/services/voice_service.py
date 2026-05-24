import logging
import time
from twilio.rest import Client
from app.config import settings

logger = logging.getLogger("app.voice_service")

class VoiceService:
    def __init__(self):
        self.client = None
        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            try:
                # Initialize Twilio client
                if settings.TWILIO_ACCOUNT_SID.startswith("AC") and len(settings.TWILIO_ACCOUNT_SID) == 34:
                    self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")

    def make_outbound_call(self, appointment_id: int, phone_number: str) -> str:
        """
        Triggers an outbound call using Twilio API.
        The call will fetch the TwiML from our server to connect to the WebSocket stream.
        """
        if not self.client:
            logger.warning("Twilio client not configured. Simulating call.")
            # If Twilio is not configured, we return a mock Call SID
            return f"mock_sid_{appointment_id}"

        # Construct the webhook URL that Twilio will request when call is answered
        twiml_url = f"{settings.BASE_URL}/api/calls/twiml?appointment_id={appointment_id}"
        status_callback_url = f"{settings.BASE_URL}/api/calls/status?appointment_id={appointment_id}"
        
        try:
            logger.info(
                "Initiating outbound call via Twilio: appointment_id=%s to=%s from=%s twiml_url=%s status_callback=%s",
                appointment_id,
                phone_number,
                settings.TWILIO_PHONE_NUMBER,
                twiml_url,
                status_callback_url,
            )
            started_at = time.perf_counter()
            call = self.client.calls.create(
                to=phone_number,
                from_=settings.TWILIO_PHONE_NUMBER,
                url=twiml_url,
                status_callback=status_callback_url,
                status_callback_method="POST",
                status_callback_event=["initiated", "ringing", "answered", "completed"]
            )
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.info(
                "Twilio call created: sid=%s status=%s direction=%s to=%s from=%s queue_time_ms=%s",
                call.sid,
                getattr(call, "status", None),
                getattr(call, "direction", None),
                getattr(call, "to", phone_number),
                getattr(call, "from_", settings.TWILIO_PHONE_NUMBER),
                elapsed_ms,
            )
            return call.sid
        except Exception as e:
            logger.exception("Error making outbound call for appointment_id=%s to=%s", appointment_id, phone_number)
            raise e

voice_service = VoiceService()
