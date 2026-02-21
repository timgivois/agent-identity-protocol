from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    master_secret: str = "dev-master-secret-change-in-production"
    jwt_secret: str = "dev-jwt-secret-change-in-production"
    database_url: str = "sqlite:///./agent_identity.db"

    class Config:
        env_file = ".env"


settings = Settings()
