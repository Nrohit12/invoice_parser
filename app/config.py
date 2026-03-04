from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    # Database Configuration
    postgres_user: str = os.environ.get("POSTGRES_USER", "postgres")
    postgres_password: str = os.environ.get("POSTGRES_PASSWORD", "postgres")
    postgres_db: str = os.environ.get("POSTGRES_DB", "fastapi_db")
    postgres_host: str = os.environ.get("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.environ.get("POSTGRES_PORT", 5432))
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fastapi_db")
    
    # Redis Configuration
    redis_host: str = os.environ.get("REDIS_HOST", "localhost")
    redis_port: int = int(os.environ.get("REDIS_PORT", 6379))
    redis_db: int = int(os.environ.get("REDIS_DB", 0))
    redis_password: Optional[str] = os.environ.get("REDIS_PASSWORD", None)
    
    # Celery Configuration
    celery_broker_url: str = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    celery_result_backend: str = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
    
    # FastAPI Configuration
    api_host: str = os.environ.get("API_HOST", "0.0.0.0")
    api_port: int = int(os.environ.get("API_PORT", 8000))
    debug: bool = os.environ.get("DEBUG", "True") == "True"
    
    # Application Settings
    app_name: str = os.environ.get("APP_NAME", "FastAPI Celery App")
    app_version: str = os.environ.get("APP_VERSION", "1.0.0")


    #Open ai api key
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()