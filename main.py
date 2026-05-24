import uvicorn
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables from .env on startup
load_dotenv()

from app.config import settings
from app.database import SessionLocal
from app.services.db_service import init_db, seed_mock_data
from app.routers import appointments, calls, frontend

# Setup logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("app.main")

# Initialize database schema and insert seed mock data
try:
    logger.info("Initializing database...")
    init_db()
    
    db = SessionLocal()
    try:
        logger.info("Seeding database with mock appointments...")
        seed_mock_data(db)
    finally:
        db.close()
        
    logger.info("Database initialized successfully.")
except Exception as e:
    logger.critical(f"Database initialization failed: {e}")

# Initialize FastAPI App
app = FastAPI(
    title="Apex Dental - Outbound AI Agent Dashboard",
    description="A FastAPI voice bot utilizing Groq, Deepgram, and Twilio for automated call confirmations.",
    version="1.0.0"
)

# Enable CORS for local testing/deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(frontend.router)
app.include_router(appointments.router)
app.include_router(calls.router)

if __name__ == "__main__":
    logger.info(f"Starting server on {settings.HOST}:{settings.PORT}")
    uvicorn.run(
        "main.py:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )
