from pydantic_settings import BaseSettings, SettingsConfigDict # type: ignore


class Settings(BaseSettings):
    environment: str = "development"
    session_cookie_secure: bool = False
    session_hours: int = 24
    session_idle_minutes: int = 240
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    cdr_api_base_url: str = "http://localhost:5000"
    cdr_api_timeout: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
