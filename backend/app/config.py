from pydantic_settings import BaseSettings
from typing import List
import sys

class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./rain_analysis.db"
    api_keys_salt: str
    cors_origins: List[str] = ["http://localhost:3000"]
    log_level: str = "INFO"
    app_title: str = "Rain Analysis API"
    app_version: str = "0.1.0"
    models_dir: str = "../models"  # Directory containing trained model pickle files
    
    class Config:
        env_file = ".env"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._validate_api_keys_salt()
    
    def _validate_api_keys_salt(self):
        """Validate that API_KEYS_SALT is not an insecure default value.
        
        Fails fast on startup if the salt is weak or matches known insecure defaults.
        This prevents accidentally deploying with placeholder credentials.
        """
        INSECURE_DEFAULTS = {
            "change-me-in-production-use-secrets-token-hex",
            "insecure-salt-change-me",
            "default",
            "secret",
            "salt",
        }
        
        if self.api_keys_salt in INSECURE_DEFAULTS:
            print(
                f"ERROR: API_KEYS_SALT is set to an insecure default value: '{self.api_keys_salt}'\n"
                f"Generate a secure salt with: python -c 'import secrets; print(secrets.token_hex(32))'\n"
                f"Then set API_KEYS_SALT in your .env file.",
                file=sys.stderr
            )
            sys.exit(1)
        
        if len(self.api_keys_salt) < 32:
            print(
                f"ERROR: API_KEYS_SALT is too short ({len(self.api_keys_salt)} characters, minimum 32 required)\n"
                f"Generate a secure salt with: python -c 'import secrets; print(secrets.token_hex(32))'\n"
                f"Then set API_KEYS_SALT in your .env file.",
                file=sys.stderr
            )
            sys.exit(1)

settings = Settings()
