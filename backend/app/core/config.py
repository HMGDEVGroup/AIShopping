from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = ""
    SERPAPI_API_KEY: str = ""

settings = Settings()
