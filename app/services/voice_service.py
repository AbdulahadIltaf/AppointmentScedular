import logging
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
        
        try:
            logger.info(f"Initiating outbound call to {phone_number} via Twilio...")
            call = self.client.calls.create(
                to=phone_number,
                from_=settings.TWILIO_PHONE_NUMBER,
                url=twiml_url
            )
            logger.info(f"Call initiated. Twilio Call SID: {call.sid}")
            return call.sid
        except Exception as e:
            logger.error(f"Error making outbound call: {e}")
            raise e

voice_service = VoiceService()
