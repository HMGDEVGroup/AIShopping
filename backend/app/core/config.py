from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central settings object.
    Render will provide env vars; locally you can use backend/.env.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # API keys
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = ""
    SERPAPI_API_KEY: str = ""

    # Versioning
    APP_VERSION: str = "0.1.0"
    BUILD_ID: str = "dev"


# ✅ MUST EXIST: other modules import this
settings = Settings()
