from typing import List, Optional, Union
from pydantic import AnyHttpUrl, field_validator, ValidationInfo
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "AutoSEM"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "your-secret-key-here"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "autosem"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "autosem"
    SQLALCHEMY_DATABASE_URI: Optional[str] = None

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> str:
        if isinstance(v, str):
            return v
        return f"postgresql://{info.data.get('POSTGRES_USER')}:{info.data.get('POSTGRES_PASSWORD')}@{info.data.get('POSTGRES_SERVER')}/{info.data.get('POSTGRES_DB')}"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # CORS
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(
        cls, v: Union[str, List[str]]
    ) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Shopify
    SHOPIFY_SHOP_DOMAIN: str = ""
    SHOPIFY_ACCESS_TOKEN: str = ""
    SHOPIFY_API_VERSION: str = "2023-10"

    # Printful
    PRINTFUL_API_KEY: str = ""

    # Google Ads
    GOOGLE_ADS_DEVELOPER_TOKEN: str = ""
    GOOGLE_ADS_CLIENT_ID: str = ""
    GOOGLE_ADS_CLIENT_SECRET: str = ""
    GOOGLE_ADS_REFRESH_TOKEN: str = ""
    GOOGLE_ADS_CUSTOMER_ID: str = ""

    # Meta Ads
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_ACCESS_TOKEN: str = ""
    META_AD_ACCOUNT_ID: str = ""

    # Microsoft Ads
    MICROSOFT_ADS_CLIENT_ID: str = ""
    MICROSOFT_ADS_CLIENT_SECRET: str = ""
    MICROSOFT_ADS_REFRESH_TOKEN: str = ""
    MICROSOFT_ADS_DEVELOPER_TOKEN: str = ""
    MICROSOFT_ADS_ACCOUNT_ID: str = ""

    # Notification settings
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    SENDGRID_API_KEY: str = ""
    SLACK_WEBHOOK_URL: str = ""

    # Budget limits
    DAILY_SPEND_LIMIT: float = 200.00
    MONTHLY_SPEND_LIMIT: float = 5000.00
    MIN_ROAS_THRESHOLD: float = 1.5
    EMERGENCY_PAUSE_LOSS: float = 500.00

    class Config:
        case_sensitive = True
        env_file = ".env"


settings = Settings()