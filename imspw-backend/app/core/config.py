from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROCESSOR_API_SECRET: str
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
