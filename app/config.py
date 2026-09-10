import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Firebase
    firebase_project_id: str = "fashion-22af0"
    firebase_private_key_id: Optional[str] = None
    firebase_private_key: Optional[str] = None
    firebase_client_email: Optional[str] = None
    firebase_client_id: Optional[str] = None
    firebase_auth_uri: str = "https://accounts.google.com/o/oauth2/auth"
    firebase_token_uri: str = "https://oauth2.googleapis.com/token"

    # Groq AI (ONLY AI provider)
    groq_api_key: Optional[str] = None
    groq_model: str = "openai/gpt-oss-20b"

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    frontend_url: str = "http://localhost:5173"

    # AI Agent (uses groq_model)
    ai_temperature: float = 0.3
    ai_max_tokens: int = 2048

    # WhatsApp Business API (Meta App credentials - NOT seller credentials)
    # These are for the ThreadOS platform app, not individual seller connections
    meta_app_id: Optional[str] = None
    meta_app_secret: Optional[str] = None
    meta_webhook_verify_token: Optional[str] = None
    
    # WAGate.app WhatsApp API
    wagate_base_url: str = "https://wagate.app"
    wagate_api_key: Optional[str] = None
    
    # Telegram Bot API
    telegram_bot_token: Optional[str] = None
    telegram_webhook_secret: Optional[str] = None
    
    # Base URL for webhook callbacks (must be HTTPS in production)
    webhook_base_url: str = "https://your-domain.com/api/v1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()