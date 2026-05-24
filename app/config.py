import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Twilio Configuration
    TWILIO_ACCOUNT_SID: str = Field(default="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    TWILIO_AUTH_TOKEN: str = Field(default="your_twilio_auth_token")
    TWILIO_PHONE_NUMBER: str = Field(default="+1xxxxxxxxxx")

    # Groq API Configuration
    GROQ_API_KEY: str = Field(default="gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

    # Deepgram API Configuration
    DEEPGRAM_API_KEY: str = Field(default="your_deepgram_api_key")

    # App Settings
    DATABASE_URL: str = Field(default="sqlite:///./voice_agent.db")
    BASE_URL: str = Field(default="http://localhost:8000")
    PORT: int = Field(default=8000)
    HOST: str = Field(default="0.0.0.0")
    OUTBOUND_RETRY_DELAYS_SECONDS: str = Field(default="8,20")
    OUTBOUND_RETRY_ON_STATUSES: str = Field(default="busy")
    DEEPGRAM_STT_ENDPOINTING_MS: int = Field(default=180)
    DEEPGRAM_STT_INTERIM_RESULTS: bool = Field(default=True)
    USER_TURN_TIMEOUT_MS: int = Field(default=1200)

    # Allow loading from .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
