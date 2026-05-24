---
title: AppointmentSceduler
emoji: 📞
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Apex Dental - Outbound Voice AI Receptionist

This repository contains a production-minded Outbound Voice AI Agent built using **FastAPI**, **SQLite**, **Twilio Media Streams**, **Groq (LLM)**, and **Deepgram (STT/TTS)**. 

The agent is designed for a realistic clinic scenario: calling patients to remind them of upcoming dental appointments, and updating the database in real-time as patients confirm, cancel, or reschedule.

## Features

- **Bidirectional Audio WebSockets**: Connects Twilio phone calls to the local FastAPI backend, forwarding live audio to Deepgram STT and playing Deepgram TTS responses back.
- **Ultra-Fast LLM (Groq)**: Uses `llama-3.3-70b-versatile` on Groq to orchestrate context-aware conversation flows with average response generation times under 150ms.
- **Local Tool Use / Function Calling**: Groq uses native tool calling to interact directly with our SQLite database (e.g. `confirm_appointment()`, `reschedule_appointment()`, `get_available_slots()`).
- **Interactive Audio Streaming**: Uses 8kHz 8-bit mono $\mu$-law audio codec for speech transcription and synthesis, matching Twilio's native telephony codec exactly and eliminating the need for complex server-side transcoding (like `ffmpeg`).
- **Barge-in Support**: Detects when the user interrupts the agent, immediately canceling the agent's speech queue on the phone to allow a natural back-and-forth flow.
- **SSE-Reactive Dashboard**: A premium Vanilla CSS glassmorphism dashboard that listens to Server-Sent Events (SSE) from the backend to display real-time call states, live transcribing, and instant database changes.

---

## Architecture Overview

```
                          +------------------------------------------+
                          |           Frontend Dashboard             |
                          | (Vanilla CSS Glassmorphic / SSE Updates) |
                          +--------------------+---------------------+
                                               ^
                                    HTTP / SSE |
                                               v
                          +--------------------+---------------------+
                          |           FastAPI Backend                |
                          |        (Uvicorn Server, main.py)         |
                          +---+----------------+-----------------+---+
                              |                |                 |
                  Read/Write  |      TwiML     |                 |  WebSocket
             +----------------+      Webhook   |                 |  Audio Stream
             |                                 |                 |
             v                                 v                 v
+------------+------------+       +------------+------------+    +----+------------+
|     SQLite Database     |       |   Twilio Voice API      |    |  Twilio Call    |
| (Appointments/CallLogs) |       | (Trigger Outbound Call) |    |  Media Stream   |
+-------------------------+       +------------+------------+    +----+------------+
                                               |                      |
                                               | Outbound Call        |
                                               v                      |
                                      +--------+--------+             |
                                      |  Patient Phone  | <-----------+
                                      +-----------------+
                                               ^
                                               | 
                                               | WebSocket Speech / Audio
                                               v
                                  +------------+------------+
                                  |  Cognitive Services     |
                                  |                         |
                                  |  - Deepgram STT/TTS     |
                                  |  - Groq Llama 3 LLM     |
                                  +-------------------------+
```

---

## API Keys & Accounts Required

This project uses services that offer **generous free tiers** so you can run it completely for free:

1. **Twilio Account**: Required to dial numbers. Twilio gives ~$15 in free trial credits upon signup.
2. **Groq API Key**: Required for the fast LLM. Free for developers (limit 14,400 tokens/min).
3. **Deepgram API Key**: Required for STT and TTS. Deepgram grants **$200 in free credits** upon signing up, which translates to hundreds of hours of free voice streaming.
4. **Ngrok**: Required to tunnel your local FastAPI port (8000) to a public address so Twilio can send webhooks to your local machine. Free to use.

---

## Setup & Running Locally

### 1. Clone & Set Up the Environment
Initialize the virtual environment and install dependencies. This project uses `uv` for ultra-fast packaging:

```bash
# Create virtual environment
uv venv

# Activate virtual environment
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

Open `.env` and fill in your values:
- `TWILIO_ACCOUNT_SID` & `TWILIO_AUTH_TOKEN`: Find these on your [Twilio Console Dashboard](https://twilio.com/console).
- `TWILIO_PHONE_NUMBER`: Purchase a trial number or use your existing number in Twilio.
- `GROQ_API_KEY`: Get one from the [Groq Console](https://console.groq.com/keys).
- `DEEPGRAM_API_KEY`: Get one from the [Deepgram Console](https://console.deepgram.com).

### 3. Expose Local Port with Ngrok
Since Twilio needs a public URL to send audio WebSockets and retrieve TwiML instructions, you must run ngrok:

```bash
ngrok http 8000
```

Ngrok will provide a URL like `https://abcdef123.ngrok-free.app`. 
Copy this URL and set it as `BASE_URL` in your `.env` file:

```env
BASE_URL=https://abcdef123.ngrok-free.app
```

### 4. Run the Application
Start the FastAPI server:

```bash
uvicorn main:app --reload
```

Open your browser and navigate to `http://localhost:8000`. You will see the Apex Dental Dashboard pre-seeded with mock appointment records ready for testing!

---

## Testing

### Integration Route Verification
To verify that all internal endpoints, database connections, and TwiML generation schemas function correctly, run the integration test script:

```bash
.venv\Scripts\python test_server.py
```

### Verifying Call Flows (Live Test)
1. Add your personal phone number (with country code, e.g. `+14155552671`) in the scheduler or use one of the pre-seeded rows by clicking its **Dial** icon.
2. Your phone will ring. Answer it.
3. Clara, the AI, will introduce herself and ask to confirm your appointment.
4. Try different conversational responses:
   - **Confirm**: *"Yes, I will be there."* -> Clara will thank you and hang up. The row status changes to **CONFIRMED** on the dashboard in real-time.
   - **Cancel**: *"Actually, I won't be able to make it. I need to cancel."* -> Clara will ask why, note it down, and update the status to **CANCELLED** with your reason displayed in the log.
   - **Reschedule**: *"I can't make that time. Can we reschedule?"* -> Clara will call the slots tool, read back available appointments, ask you to choose, and update the table in real-time once you confirm.
5. Hang up the call. The dashboard will instantly show the full transcript and a neat summary of the call.
