import os

def load_config():
    """
    Load environment variables from .env file.
    Assumes .env is in the project root or accessible via defaults.
    """
    pass

class Settings:
    @property
    def DATABASE_URL(self):
        url = os.getenv("DATABASE_URL")
        if not url:
            user = os.getenv("POSTGRES_USER", "postgres")
            password = os.getenv("POSTGRES_PASSWORD", "postgres")
            server = os.getenv("POSTGRES_SERVER", "localhost")
            db = os.getenv("POSTGRES_DB", "qunkong_service")
            return f"postgresql+asyncpg://{user}:{password}@{server}/{db}"

    @property
    def DATABASE_URL_SYNC(self):
         user = os.getenv("POSTGRES_USER", "postgres")
         password = os.getenv("POSTGRES_PASSWORD", "postgres")
         server = os.getenv("POSTGRES_SERVER", "localhost")
         db = os.getenv("POSTGRES_DB", "qunkong_service")
         return f"postgresql://{user}:{password}@{server}/{db}"

settings = Settings()
