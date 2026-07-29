from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List

class Settings(BaseSettings):
    database_url: str
    api_keys_salt: str
    cors_origins: List[str] = []
    log_level: str = "INFO"
    app_title: str = "Rain Analysis API"
    app_version: str = "0.1.0"
    models_dir: str = "../models"  # Directory containing trained model pickle files
    
    @field_validator("api_keys_salt")
    @classmethod
    def validate_salt(cls, v: str) -> str:
        """Validate that API_KEYS_SALT is secure and not using default value."""
        if v == "change-me-in-production-use-secrets-token-hex":
            raise ValueError(
                "API_KEYS_SALT must be changed from default value. "
                "Generate a secure salt with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if len(v) < 32:
            raise ValueError(
                f"API_KEYS_SALT must be at least 32 characters (got {len(v)}). "
                "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v
    
    class Config:
        env_file = ".env"

settings = Settings()
