from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Loads environment variables from backend/.env
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = ""        # optional; if set, we skip ListModels for speed/quota
    SERPAPI_API_KEY: str = ""


settings = Settings()
