from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./rain_analysis.db"
    api_keys_salt: str
    cors_origins: List[str] = ["http://localhost:3000"]
    log_level: str = "INFO"
    app_title: str = "Rain Analysis API"
    app_version: str = "0.1.0"
    
    class Config:
        env_file = ".env"

settings = Settings()
