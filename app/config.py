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

    # Allow loading from .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
