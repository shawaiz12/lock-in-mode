import ssl
import uuid
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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
    # Encryption to Postgres (ADR 0028). "prefer" (asyncpg's own default) suits local
    # Docker, which has no TLS. Hosted Postgres (Supabase) needs "verify-full": encrypted
    # AND the server's certificate checked, so nobody in the middle can pretend to be it.
    postgres_sslmode: Literal["disable", "prefer", "require", "verify-full"] = "prefer"
    # The certificate authority to trust instead of the system's (ADR 0030), as PEM text:
    # "-----BEGIN CERTIFICATE----- ...". Supabase signs its database certificates with
    # its own CA ("Supabase Root 2021 CA"), which no system trusts, so verify-full needs
    # it. Empty: trust the system's certificates (most other hosts). A value pasted
    # on one line with literal \n between lines works too.
    postgres_ssl_root_cert: str | None = None
    # Connecting through a transaction pooler (ADR 0031): Supabase's port 6543, used by
    # the API on Vercel. The pooler lends us a real database connection for ONE
    # transaction, then gives it to someone else. Two consequences:
    # - prepared statements (asyncpg caches them per connection) don't survive the swap,
    #   so they're switched off;
    # - the pooler already pools, so the app opens a fresh connection per request instead
    #   of keeping its own pool (connections parked in a frozen serverless instance would
    #   only go stale). See core/db.py.
    # Migrations, the seed, backups and the cleanup job use the session pooler (5432).
    postgres_transaction_pooler: bool = False

    # Which commit this server runs (ADR 0028, 0031). The deploy job passes the commit id
    # (vercel deploy --env, or a Docker build argument); /health/live reports it, so CI
    # can see the new version is live.
    app_version: str = "dev"

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
    # rediss = TLS. Plain redis:// only for this machine or a compose service (ADR 0031).
    redis_url: str = "redis://localhost:6379/0"

    # Rate limits (ADR 0008): max requests per client IP per minute, per sign-in endpoint.
    # Generous on purpose: mobile carriers put many phones behind one shared IP.
    auth_rate_limit_per_minute: int = 20

    # Behind a hosting proxy (ADR 0028), the connection comes from the proxy, and the real
    # caller is in the X-Forwarded-For header. 0 = no proxy: use the connection's address
    # (local). 1 = one proxy in front: trust only the LAST entry, the one our own proxy
    # added. Entries before it come from the caller and can be made up.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

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

    @field_validator("redis_url")
    @classmethod
    def remote_redis_must_use_tls(cls, value: str) -> str:
        # Found going live (ADR 0031): a redis:// URL to Upstash connects, then the server
        # hangs up (it only speaks TLS), and rate limiting quietly switches itself off.
        # A Redis on another machine is one whose host has a dot (a real domain or an IP
        # address): localhost and compose service names ("redis") have none.
        parts = urlsplit(value)
        host = parts.hostname or ""
        local = host in {"localhost", "127.0.0.1", "::1"} or "." not in host
        if parts.scheme == "redis" and not local:
            raise ValueError(
                "REDIS_URL must start with rediss:// (two s's: TLS) for a Redis on another "
                "machine. Copy the rediss:// URL from Upstash, not the redis-cli line."
            )
        if parts.scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must start with rediss:// (or redis:// locally).")
        return value

    @field_validator("postgres_ssl_root_cert")
    @classmethod
    def root_cert_must_be_a_certificate(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        pem = value.strip().replace("\\n", "\n")
        try:
            ssl.create_default_context(cadata=pem)
        except (ssl.SSLError, ValueError) as error:
            raise ValueError(
                "POSTGRES_SSL_ROOT_CERT must be the PEM text of a CA certificate "
                "(-----BEGIN CERTIFICATE----- ... -----END CERTIFICATE-----)."
            ) from error
        return pem

    @model_validator(mode="after")
    def root_cert_needs_verify_full(self) -> "Settings":
        # Any other mode would never look at the certificate: refuse rather than
        # quietly connect without the check someone thought they had turned on.
        if self.postgres_ssl_root_cert and self.postgres_sslmode != "verify-full":
            raise ValueError("POSTGRES_SSL_ROOT_CERT only works with POSTGRES_SSLMODE=verify-full.")
        return self

    @property
    def database_url(self) -> URL:
        # SQLAlchemy's own cache of prepared statements, on top of asyncpg's: off behind
        # a transaction pooler, like asyncpg's (database_connect_args).
        query = {"prepared_statement_cache_size": "0"} if self.postgres_transaction_pooler else {}
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
            query=query,
        )

    @property
    def database_connect_args(self) -> dict[str, Any]:
        """Extra asyncpg options, shared by the app's engine and Alembic's."""
        # timeout: give up connecting after 5 s instead of hanging a request.
        ssl_option: str | ssl.SSLContext = self.postgres_sslmode
        if self.postgres_sslmode == "verify-full":
            # Given the plain string, asyncpg looks for ~/.postgresql/root.crt like psql
            # does, which no server image has. Python's default context checks the
            # certificate AND the host name against the system's trusted certificates,
            # the same ones a browser uses: exactly verify-full, nothing to install.
            # With POSTGRES_SSL_ROOT_CERT it trusts ONLY that CA (ADR 0030), still
            # checking the host name.
            ssl_option = ssl.create_default_context(cadata=self.postgres_ssl_root_cert)
        args: dict[str, Any] = {"timeout": 5, "ssl": ssl_option}
        if self.postgres_transaction_pooler:
            # No cached prepared statements, and a never-reused name for the few that
            # SQLAlchemy still prepares, so two clients sharing one database connection
            # can't collide on "__asyncpg_stmt_1__" (SQLAlchemy's documented setup).
            args["statement_cache_size"] = 0
            args["prepared_statement_name_func"] = _unique_statement_name
        return args


def _unique_statement_name() -> str:
    return f"__asyncpg_{uuid.uuid4()}__"


settings = Settings()
