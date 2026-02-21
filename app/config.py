from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    app_name: str = "Agent Marketplace"
    app_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    environment: str = "development"
    debug: bool = False

    # Database — PostgreSQL in prod, SQLite for local dev
    database_url: str = "sqlite:///./agent_identity.db"

    # Secrets
    master_secret: str = "dev-master-secret-change-in-production-32chars"
    jwt_secret: str = "dev-jwt-secret-change-in-production"
    api_key_prefix: str = "ak"

    # Email (Resend)
    resend_api_key: str = ""
    email_from: str = "noreply@agentmarketplace.com"
    email_from_name: str = "Agent Marketplace"

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # Rate limiting
    rate_limit_per_minute: int = 100
    rate_limit_agent_post: int = 1  # posts per 30 min

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def db_connect_args(self) -> dict:
        if "sqlite" in self.database_url:
            return {"check_same_thread": False}
        return {}


settings = Settings()
