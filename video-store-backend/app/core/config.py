from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    ALLOWED_ORIGINS: str = "*"

    # ── Telegram ──────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = ""
    # Max age of Telegram initData (auth_date). Refresh re-uses the same initData,
    # so a long-open Mini App needs a window at least as long as a session.
    TELEGRAM_AUTH_MAX_AGE_SECONDS: int = 86400

    # ── JWT ───────────────────────────────────────────────────────────────
    JWT_PRIVATE_KEY_PATH: str = "./private.pem"
    JWT_PUBLIC_KEY_PATH: str = "./public.pem"
    JWT_ALGORITHM: str = "RS256"
    JWT_ACCESS_TOKEN_EXPIRE_HOURS: int = 24

    # ── Firebase ──────────────────────────────────────────────────────────
    FIREBASE_SERVICE_ACCOUNT_PATH: str = "./firebase-service-account.json"
    FIREBASE_PROJECT_ID: str = ""

    # ── Encryption ────────────────────────────────────────────────────────
    SOURCE_URL_ENCRYPTION_KEY: str = ""

    # ── Binance ───────────────────────────────────────────────────────────
    BINANCE_PAY_API_KEY: str = ""
    BINANCE_PAY_API_SECRET: str = ""
    BINANCE_PAY_MERCHANT_ID: str = ""
    BINANCE_PAY_BASE_URL: str = "https://bpay.binanceapi.com"

    # ── Monetag ───────────────────────────────────────────────────────────
    MONETAG_CALLBACK_SECRET: str = ""

    # ── Admin ─────────────────────────────────────────────────────────────
    ADMIN_USERNAME: str = "admin"
    # Simplest: set ADMIN_PASSWORD (plain). ADMIN_PASSWORD_HASH (bcrypt) still works.
    ADMIN_PASSWORD: str = ""
    ADMIN_PASSWORD_HASH: str = ""

    # ── Public URLs (used in Binance Pay callbacks) ───────────────────────
    # Empty = auto (Render's RENDER_EXTERNAL_URL).
    PUBLIC_API_BASE_URL: str = ""
    TELEGRAM_BOT_USERNAME: str = "videostore_bot"
    # Public https URL of the deployed Mini App (frontend). Optional: when empty the
    # first https entry of ALLOWED_ORIGINS is used for the bot's "open" button.
    MINI_APP_URL: str = ""

    # ── Rate limiting (in-memory, per process) ────────────────────────────
    RATE_LIMIT_ENABLED: bool = True

    # ── Derived helpers ───────────────────────────────────────────────────
    def model_post_init(self, __context) -> None:
        import os
        if self.ADMIN_PASSWORD and not self.ADMIN_PASSWORD_HASH:
            from passlib.hash import bcrypt
            self.ADMIN_PASSWORD_HASH = bcrypt.hash(self.ADMIN_PASSWORD[:72])
        if not self.PUBLIC_API_BASE_URL:
            self.PUBLIC_API_BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
        if not self.FIREBASE_PROJECT_ID:
            try:
                import json
                with open(self.FIREBASE_SERVICE_ACCOUNT_PATH) as f:
                    self.FIREBASE_PROJECT_ID = json.load(f).get("project_id", "")
            except Exception:
                pass

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def mini_app_url(self) -> str:
        url = self.MINI_APP_URL.strip()
        if not url:
            url = next((o for o in self.allowed_origins_list if o.startswith("https://")), "")
        return url.rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


def validate_runtime_config(s: "Settings | None" = None) -> list[str]:
    """
    Returns a list of configuration problems (empty = OK).
    Kept deliberately light: only the admin login is mandatory. Everything else
    (Binance, Monetag, ...) is optional and just disables that feature.
    """
    s = s or settings
    problems: list[str] = []
    if not s.ADMIN_PASSWORD_HASH:
        problems.append("ADMIN_PASSWORD is not set (admin login disabled)")
    return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
