from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        extra="ignore",
        # Never echo raw values in validation errors: they can contain secrets.
        hide_input_in_errors=True,
    )

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Auth (ADR 0005). No default: the app refuses to start without a real secret.
    jwt_secret: SecretStr
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 60
    # Guests (ADR 0027): their refresh token is their only way back in, so it lasts a
    # year from the last time the app used it. Google/Apple accounts can sign in again.
    guest_refresh_token_ttl_days: int = 365

    # Sign in with Google / Apple (ADR 0005). Empty means that provider is switched off,
    # so the API runs fine before the mobile app exists.
    # GOOGLE_CLIENT_IDS is a JSON list, one id per app build: '["<android>", "<ios>"]'
    google_client_ids: list[str] = []
    apple_bundle_id: str | None = None

    # Redis (rate limiting now; caching and Celery later). A URL, because hosted Redis
    # (e.g. Upstash) hands you one: rediss://default:<password>@<host>:6379
    redis_url: str = "redis://localhost:6379/0"

    # Rate limits (ADR 0008): max requests per client IP per minute, per sign-in endpoint.
    # Generous on purpose: mobile carriers put many phones behind one shared IP.
    auth_rate_limit_per_minute: int = 20

    # Deleting accounts (ADR 0024): how often the API erases accounts whose 30 days are
    # over. 0 switches the background task off (sign-in still erases a due account).
    account_cleanup_interval_seconds: int = 3600

    # "Download my data" (ADR 0027): exports per account per hour.
    export_rate_limit_per_hour: int = 3

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_long(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return value

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


settings = Settings()
