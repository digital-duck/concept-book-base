from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    spl_dir: Path = Path.home() / "projects/digital-duck/SPL.py"
    public_domains: Path = Path(__file__).parent.parent / "public" / "domains"
    llm: str = "claude_cli:claude-sonnet-4-6"
    default_model: str = "gemma4"
    compare_cache_ttl: int = 86400  # seconds; 0 = never expire
    spl_while_max_iter: int = 50
    spl_max_llm_calls: int = 50

    model_config = {"env_prefix": "CB_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
