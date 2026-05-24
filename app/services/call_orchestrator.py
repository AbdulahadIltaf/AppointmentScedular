import os
import json
import base64
import asyncio
import httpx
import logging
from datetime import datetime
from fastapi import WebSocket
from sqlalchemy.orm import Session
from groq import Groq

from app.config import settings
from app.services.db_service import (
    get_appointment,
    update_appointment_status,
    reschedule_appointment,
    get_available_slots_spoken,
    create_call_log,
    update_call_log,
    format_datetime_spoken
)

logger = logging.getLogger("app.call_orchestrator")

# SSE Broadcaster for real-time dashboard updates
class SSEBroadcaster:
    def __init__(self):
        self.listeners = set()

    def subscribe(self, queue: asyncio.Queue):
        self.listeners.add(queue)

    def unsubscribe(self, queue: asyncio.Queue):
        self.listeners.discard(queue)

    async def broadcast(self, event_type: str, data: dict):
        message = json.dumps({"event": event_type, "data": data})
        for queue in list(self.listeners):
            await queue.put(message)

broadcaster = SSEBroadcaster()

# Conversation Orchestrator
class CallOrchestrator:
    def __init__(self, websocket: WebSocket, appointment_id: int, db: Session):
        self.websocket = websocket
        self.appointment_id = appointment_id
        self.db = db
        self.stream_sid = None
        self.call_sid = None
        
        # Initialize Groq client
        self.groq_client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = "llama-3.3-70b-versatile"
        
        # Audio playback control
        self.play_task = None
        self.is_playing = False
        self.interrupt_event = asyncio.Event()
        
        # Conversation state
        self.appointment = get_appointment(db, appointment_id)
        self.patient_name = self.appointment.patient_name if self.appointment else "Patient"
        self.appt_time_spoken = (
            format_datetime_spoken(self.appointment.appointment_time)
            if self.appointment else "unknown time"
        )
        self.notes = self.appointment.notes if self.appointment else ""
        
        # Initialize history with system prompt
        self.history = [
            {"role": "system", "content": self.get_system_prompt()}
        ]
        
        # Accumulate transcript
        self.transcript_history = []
        self.final_transcript = ""

    def get_system_prompt(self) -> str:
        current_time_str = datetime.now().strftime("%I:%M %p on %A, %B %d, %Y")
        return f"""
You are Clara, a friendly, warm, and professional receptionist calling from "Apex Dental".
Your goal is to remind the patient, {self.patient_name}, about their upcoming appointment and get a confirmation.

Appointment Details:
- Patient Name: {self.patient_name}
- Appointment Date/Time: {self.appt_time_spoken}
- Notes/Dentist: {self.notes}
- Current Time: {current_time_str}

Conversation Flow Guidelines:
1. **Greeting**: Politely greet {self.patient_name}, state you are calling from Apex Dental, and remind them of their appointment on {self.appt_time_spoken}. Ask if they are still able to make it.
2. **Handle Confirmation**:
   - If they confirm, thank them warmly and call the `confirm_appointment` tool. Then inform them we look forward to seeing them.
3. **Handle Cancellation**:
   - If they cannot make it and want to cancel, ask for the reason, call the `cancel_appointment` tool, and tell them the appointment is cancelled. Offer to help them reschedule in the future if they wish.
4. **Handle Rescheduling**:
   - If they ask to reschedule, call the `get_available_slots` tool to retrieve available appointments, present the slots clearly (limit to 3 slots spoken at a time so they are easy to remember), and ask which one they prefer.
   - Once they pick a slot, call the `reschedule_appointment` tool and confirm the new time with them.
5. **Tone & Constraints**:
   - Keep your responses concise (1-2 sentences maximum). People on the phone don't like listening to long monologues.
   - Do NOT say "Sure!" or "Awesome!" repeatedly. Be professional, empathetic, and polite.
   - Make sure to call the correct tools whenever the patient makes a decision.
"""

    def get_tools_schema(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "confirm_appointment",
                    "description": "Confirm the patient's appointment in the database.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_appointment",
                    "description": "Cancel the patient's appointment and record the reason.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "The reason the patient gave for cancelling the appointment."
                            }
                        },
                        "required": ["reason"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_available_slots",
                    "description": "Get list of available mock times for rescheduling an appointment.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "reschedule_appointment",
                    "description": "Reschedule the patient's appointment to a new date and time.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "new_time": {
                                "type": "string",
                                "description": "The selected new appointment time in ISO format (e.g. '2026-05-25T09:00:00')."
                            }
                        },
                        "required": ["new_time"]
                    }
                }
            }
        ]

    async def execute_tool(self, name: str, args: dict) -> str:
        """Executes the local database operation for a tool call."""
        logger.info(f"Executing tool {name} with args: {args}")
        await broadcaster.broadcast("status", {"text": f"Clara is updating database: {name}..."})
        
        try:
            if name == "confirm_appointment":
                update_appointment_status(self.db, self.appointment_id, "CONFIRMED")
                await broadcaster.broadcast("db_update", {
                    "appointment_id": self.appointment_id,
                    "status": "CONFIRMED",
                    "message": "Appointment Confirmed via Voice AI"
                })
                return json.dumps({"success": True, "message": "Appointment successfully confirmed in the database."})
                
            elif name == "cancel_appointment":
                reason = args.get("reason", "No reason provided")
                update_appointment_status(self.db, self.appointment_id, "CANCELLED", reason)
                await broadcaster.broadcast("db_update", {
                    "appointment_id": self.appointment_id,
                    "status": "CANCELLED",
                    "cancellation_reason": reason,
                    "message": f"Appointment Cancelled: {reason}"
                })
                return json.dumps({"success": True, "message": "Appointment successfully cancelled."})
                
            elif name == "get_available_slots":
                slots = get_available_slots_spoken()
                return json.dumps({"success": True, "slots": slots})
                
            elif name == "reschedule_appointment":
                new_time_iso = args.get("new_time")
                new_time = datetime.fromisoformat(new_time_iso)
                reschedule_appointment(self.db, self.appointment_id, new_time)
                new_time_spoken = format_datetime_spoken(new_time)
                await broadcaster.broadcast("db_update", {
                    "appointment_id": self.appointment_id,
                    "status": "RESCHEDULED",
                    "appointment_time": new_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "message": f"Appointment Rescheduled to {new_time_spoken}"
                })
                return json.dumps({
                    "success": True, 
                    "new_time_spoken": new_time_spoken,
                    "message": "Appointment successfully rescheduled."
                })
        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return json.dumps({"success": False, "error": str(e)})
            
        return json.dumps({"success": False, "error": "Unknown tool"})

    async def speak(self, text: str):
        """Sends the text to Deepgram TTS and streams the returned audio to Twilio."""
        if not self.stream_sid:
            logger.warning("No stream SID. Cannot speak.")
            return

        # Cancel any active playback
        await self.stop_speaking()

        await broadcaster.broadcast("status", {"text": "Clara is speaking..."})
        logger.info(f"AI Speaking: {text}")
        self.transcript_history.append(f"Clara: {text}")
        self.final_transcript += f"Clara: {text}\n"
        
        await broadcaster.broadcast("transcript", {
            "role": "assistant",
            "text": text,
            "full": "\n".join(self.transcript_history)
        })

        try:
            # Deepgram TTS Aura API endpoint
            # We request 'mulaw' encoding and '8000' sample rate, matching Twilio's requirements
            tts_url = "https://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=mulaw&sample_rate=8000"
            headers = {
                "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {"text": text}

            async with httpx.AsyncClient() as client:
                response = await client.post(tts_url, headers=headers, json=payload, timeout=20.0)
                if response.status_code != 200:
                    logger.error(f"Deepgram TTS API error: {response.status_code} - {response.text}")
                    return
                
                audio_data = response.content

            # Play the audio in chunks to Twilio
            self.play_task = asyncio.create_task(self._send_audio_chunks(audio_data))
            await self.play_task
        except asyncio.CancelledError:
            logger.info("Speech playback cancelled (barge-in or connection closed).")
        except Exception as e:
            logger.error(f"Error in speaking: {e}")

    async def _send_audio_chunks(self, audio_data: bytes):
        self.is_playing = True
        self.interrupt_event.clear()
        
        # Audio properties: 8000 Hz, 8-bit, 1 channel mulaw = 8000 bytes per second
        # We'll send chunks of 1600 bytes (equivalent to 200ms of audio)
        chunk_size = 1600
        delay = 0.20  # 200ms
        
        try:
            for i in range(0, len(audio_data), chunk_size):
                if self.interrupt_event.is_set():
                    logger.info("Audio playback interrupted.")
                    break
                    
                chunk = audio_data[i:i + chunk_size]
                base64_audio = base64.b64encode(chunk).decode("utf-8")
                
                # Send the media frame to Twilio
                await self.websocket.send_json({
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {
                        "payload": base64_audio
                    }
                })
                
                # Yield control to allow interrupts to be processed
                await asyncio.sleep(delay)
        finally:
            self.is_playing = False
            await broadcaster.broadcast("status", {"text": "Clara is listening..."})

    async def stop_speaking(self):
        """Stops any current audio playback and clears the Twilio queue."""
        if self.is_playing:
            self.interrupt_event.set()
            if self.play_task:
                self.play_task.cancel()
            
            # Send a clear message to Twilio to stop playing buffered audio
            if self.stream_sid:
                await self.websocket.send_json({
                    "event": "clear",
                    "streamSid": self.stream_sid
                })
            logger.info("Sent clear event to Twilio to halt audio playback.")

    async def generate_response(self, user_text: str = None):
        """Queries Groq to generate a response, handling tool calls if necessary."""
        if user_text:
            self.history.append({"role": "user", "content": user_text})
            self.transcript_history.append(f"Patient: {user_text}")
            self.final_transcript += f"Patient: {user_text}\n"
            
            await broadcaster.broadcast("transcript", {
                "role": "user",
                "text": user_text,
                "full": "\n".join(self.transcript_history)
            })

        await broadcaster.broadcast("status", {"text": "Clara is thinking..."})
        
        try:
            # We run this in an executor because the groq client is synchronous
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.groq_client.chat.completions.create(
                    model=self.model,
                    messages=self.history,
                    tools=self.get_tools_schema(),
                    tool_choice="auto",
                    temperature=0.4,
                    max_tokens=256
                )
            )

            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            # Handle response
            if response_message.content:
                # Normal verbal response
                self.history.append({"role": "assistant", "content": response_message.content})
                # Speak it
                await self.speak(response_message.content)

            if tool_calls:
                # Append assistant tool call request to history
                self.history.append(response_message)
                
                # Execute each tool call
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    # Execute tool locally
                    tool_result = await self.execute_tool(tool_name, tool_args)
                    
                    # Append result to history
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": tool_result
                    })
                
                # Recursive call to let the model generate text based on the tool results
                await self.generate_response()

        except Exception as e:
            logger.error(f"Error generating LLM response from Groq: {e}")
            await self.speak("I'm sorry, I'm having a technical difficulty. Can you please repeat that?")

    async def connect_deepgram_stt(self) -> WebSocket:
        """Establishes a WebSocket connection to Deepgram's live transcription API."""
        headers = {
            "Authorization": f"Token {settings.DEEPGRAM_API_KEY}"
        }
        # Nov-2 model for telephony 8kHz mulaw
        dg_url = "wss://api.deepgram.com/v1/listen?encoding=mulaw&sample_rate=8000&channels=1&model=nova-2-phonecall&smart_format=true&endpointing=500"
        
        try:
            import websockets
            dg_ws = await websockets.connect(dg_url, extra_headers=headers)
            logger.info("Connected to Deepgram STT WebSocket.")
            return dg_ws
        except Exception as e:
            logger.error(f"Failed to connect to Deepgram STT: {e}")
            raise e

    async def run(self):
        """Starts the voice agent call orchestration loop."""
        # 1. Connect to Deepgram STT
        try:
            dg_ws = await self.connect_deepgram_stt()
        except Exception:
            await self.websocket.close()
            return

        # Create a database call log entry
        db_log = create_call_log(self.db, self.appointment_id)
        
        # Twilio stream states
        self.stream_sid = None
        
        async def receive_from_twilio():
            """Task to listen to the Twilio WebSocket and forward audio to Deepgram STT."""
            nonlocal db_log
            try:
                while True:
                    data = await self.websocket.receive_text()
                    packet = json.loads(data)
                    
                    if packet["event"] == "connected":
                        logger.info("Twilio media stream connected.")
                        
                    elif packet["event"] == "start":
                        self.stream_sid = packet["start"]["streamSid"]
                        self.call_sid = packet["start"]["callSid"]
                        logger.info(f"Twilio stream started: {self.stream_sid}, Call SID: {self.call_sid}")
                        
                        # Update DB Log with call_sid
                        db_log = update_call_log(self.db, self.call_sid, "in-progress")
                        await broadcaster.broadcast("call_state", {
                            "appointment_id": self.appointment_id,
                            "twilio_call_sid": self.call_sid,
                            "status": "in-progress"
                        })
                        
                        # Clara speaks first to start the call
                        # Introduce and ask for confirmation
                        greeting_text = (
                            f"Hello {self.patient_name}, this is Clara calling from Apex Dental. "
                            f"I'm calling to confirm your appointment scheduled for {self.appt_time_spoken}. "
                            f"Are you still able to attend?"
                        )
                        # Launch greeting in background so we can listen simultaneously
                        asyncio.create_task(self.speak(greeting_text))
                        self.history.append({"role": "assistant", "content": greeting_text})
                        
                    elif packet["event"] == "media":
                        # We got audio from Twilio (8kHz mulaw)
                        media = packet["media"]
                        if media["track"] == "inbound":
                            payload = base64.b64decode(media["payload"])
                            # Forward raw audio chunk directly to Deepgram STT
                            await dg_ws.send(payload)
                            
                    elif packet["event"] == "stop":
                        logger.info("Twilio stream stopped.")
                        break
            except Exception as e:
                logger.error(f"Error in receive_from_twilio: {e}")
            finally:
                # Send empty close packet to Deepgram
                try:
                    await dg_ws.send(json.dumps({"type": "CloseStream"}))
                except Exception:
                    pass

        async def receive_from_deepgram():
            """Task to listen for transcripts from Deepgram and trigger LLM generation."""
            try:
                async for message in dg_ws:
                    data = json.loads(message)
                    
                    # Deepgram sends metadata or channel transcript information
                    channel = data.get("channel", {})
                    alternatives = channel.get("alternatives", [{}])
                    transcript = alternatives[0].get("transcript", "").strip()
                    
                    if not transcript:
                        continue
                        
                    # Handle Barge-in (interrupting the agent)
                    if self.is_playing:
                        # User spoke, so stop Clara immediately
                        logger.info(f"Barge-in detected! User transcript: '{transcript}'")
                        await self.stop_speaking()
                    
                    is_final = data.get("is_final", False)
                    speech_final = data.get("speech_final", False)
                    
                    if is_final:
                        logger.info(f"User speaking (final): {transcript}")
                        await broadcaster.broadcast("status", {"text": f"Patient: '{transcript}'"})
                        
                        # If Deepgram determines speech has concluded
                        if speech_final or len(transcript.split()) >= 2:
                            # Run LLM response generation in background
                            # We check if there's no active speech response already being processed
                            asyncio.create_task(self.generate_response(transcript))
            except Exception as e:
                logger.error(f"Error in receive_from_deepgram: {e}")

        # Run Twilio receiver and Deepgram receiver concurrently
        try:
            await asyncio.gather(receive_from_twilio(), receive_from_deepgram())
        except Exception as e:
            logger.error(f"Error in WebSocket execution loop: {e}")
        finally:
            logger.info("Call socket closed. Saving records.")
            await self.stop_speaking()
            try:
                await dg_ws.close()
            except Exception:
                pass
                
            # Perform final post-call summary and updates
            await self.finalize_call_log(db_log)

    async def finalize_call_log(self, db_log):
        """Triggered when the call is ended. Generates a summary and writes the logs to DB."""
        await broadcaster.broadcast("status", {"text": "Call ended. Generating summary..."})
        
        # Summarize the call using Groq
        summary = "No conversation occurred."
        if len(self.transcript_history) > 1:
            try:
                history_text = "\n".join(self.transcript_history)
                loop = asyncio.get_event_loop()
                summary_response = await loop.run_in_executor(
                    None,
                    lambda: self.groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[
                            {"role": "system", "content": "You are a receptionist assistant. Summarize the following phone call transcript in 1-2 concise sentences. Focus on whether the appointment was confirmed, cancelled, or rescheduled, and any next steps."},
                            {"role": "user", "content": history_text}
                        ],
                        max_tokens=100
                    )
                )
                summary = summary_response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Failed to generate call summary: {e}")
                summary = "Failed to generate summary due to technical error."

        # Save to Database
        if self.call_sid:
            # Fetch status/duration from Twilio if we wanted to, or mock
            update_call_log(
                self.db, 
                self.call_sid, 
                status="completed",
                transcript=self.final_transcript,
                summary=summary,
                duration=60 # Mock duration
            )
            
            # Broadcast final call summary to UI
            await broadcaster.broadcast("call_ended", {
                "appointment_id": self.appointment_id,
                "twilio_call_sid": self.call_sid,
                "status": "completed",
                "transcript": self.final_transcript,
                "summary": summary
            })
        else:
            # Handled a mock call
            mock_sid = f"mock_sid_{self.appointment_id}"
            update_call_log(
                self.db,
                mock_sid,
                status="completed",
                transcript=self.final_transcript,
                summary=summary,
                duration=30
            )
            await broadcaster.broadcast("call_ended", {
                "appointment_id": self.appointment_id,
                "twilio_call_sid": mock_sid,
                "status": "completed",
                "transcript": self.final_transcript,
                "summary": summary
            })
        
        await broadcaster.broadcast("status", {"text": "Call Completed."})
