from pydantic_settings import BaseSettings
from pydantic import Field
import os
from pathlib import Path

class Settings(BaseSettings):
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    database_url: str = Field(default="sqlite:///data/stock_lab.db", alias="DATABASE_URL")
    yfinance_enabled: bool = Field(default=True, alias="YFINANCE_ENABLED")
    ai_cache_ttl_days: int = 7
    data_dir: Path = Path("data")
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()

def get_db_path() -> Path:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///",""))
    return Path("data/stock_lab.db")
