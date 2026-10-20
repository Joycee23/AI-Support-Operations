from dataclasses import dataclass
import os
from urllib.parse import urlsplit
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    database_url: str
    gemini_api_key: str
    gemini_model: str
    embedding_model: str
    upload_dir: str
    cors_origins: list[str]
    ai_provider: str = "gemini"
    ninerouter_api_key: str = ""
    ninerouter_base_url: str = "http://localhost:20128/v1"
    ninerouter_model: str = "codexlite/gpt-6-luna"
    ninerouter_fallback_models: tuple[str, ...] = ("codexlite/gpt-6-sol",)
    ninerouter_gemini_fallback: bool = True
    gemini_fallback_models: tuple[str, ...] = ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite")

def get_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL", "").strip()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    missing = [name for name, value in (("DATABASE_URL", database_url), ("GEMINI_API_KEY", api_key)) if not value]
    if missing:
        raise RuntimeError(
            "Thiếu cấu hình bắt buộc: " + ", ".join(missing) + ". "
            "Sao chép .env.example thành .env, khởi động PostgreSQL bằng docker compose up -d db, "
            "rồi cấu hình GEMINI_API_KEY trước khi chạy API."
        )
    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    router_key = os.getenv("NINEROUTER_API_KEY", "").strip()
    router_url = os.getenv("NINEROUTER_BASE_URL", "http://localhost:20128/v1").strip().rstrip('/')
    router_model = os.getenv("NINEROUTER_MODEL", "codexlite/gpt-6-luna").strip()
    if provider not in {"gemini", "9router"}:
        raise RuntimeError("AI_PROVIDER phải là gemini hoặc 9router.")
    if provider == "9router":
        parsed = urlsplit(router_url)
        if not router_key or not router_model:
            raise RuntimeError("Điền NINEROUTER_API_KEY và NINEROUTER_MODEL trước khi bật AI_PROVIDER=9router.")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError("NINEROUTER_BASE_URL phải là URL HTTP(S), không chứa key hoặc thông tin đăng nhập.")
    return Settings(
        ai_provider=provider,
        ninerouter_api_key=router_key,
        ninerouter_base_url=router_url,
        ninerouter_model=router_model,
        ninerouter_fallback_models=tuple(x.strip() for x in os.getenv("NINEROUTER_FALLBACK_MODELS", "codexlite/gpt-6-sol").split(',') if x.strip()),
        ninerouter_gemini_fallback=os.getenv("NINEROUTER_GEMINI_FALLBACK", "true").strip().lower() == "true",
        database_url=database_url,
        gemini_api_key=api_key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        gemini_fallback_models=tuple(
            model.strip() for model in os.getenv(
                "GEMINI_FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.5-flash,gemini-3.1-flash-lite"
            ).split(",") if model.strip()
        ),
        embedding_model=os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
        upload_dir=os.getenv("UPLOAD_DIR", "./data/uploads"),
        cors_origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if x.strip()],
    )


def browser_origins() -> list[str]:
    """Explicit deployment origin is trusted; arbitrary forwarded headers are not."""
    origins = [value.strip().rstrip('/') for value in os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',') if value.strip()]
    public = urlsplit(os.getenv('APP_PUBLIC_URL', '').strip())
    if public.scheme in {'http', 'https'} and public.netloc and not public.username and not public.password:
        origins.append(f'{public.scheme}://{public.netloc}')
    return list(dict.fromkeys(origins))
