from pathlib import Path
from pydantic import field_validator
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

_REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(_REPO_ROOT / ".env", override=True)


class Settings(BaseSettings):
    spl_dir: Path = Path.home() / "projects/digital-duck/SPL.py"
    public_domains: Path = _REPO_ROOT / "public" / "domains"
    llm: str = "claude_cli:claude-sonnet-5"
    default_model: str = "sonnet"
    spl_while_max_iter: int = 50
    spl_max_llm_calls: int = 50

    # User-supplied API keys for adapters that need one (set from the
    # Settings page, kept in-memory only like every other setting here —
    # never echoed back to the browser, only injected into the spl3
    # subprocess env at generate time; see executor.py's _ADAPTER_ENV_VAR).
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""

    model_config = {"env_prefix": "CB_", "extra": "ignore"}

    # `.env` values for these arrive as literal, unresolved strings —
    # CB_SPL_DIR=~/... keeps its `~` (pydantic doesn't expand it), and
    # CB_PUBLIC_DOMAINS=./public/domains stays relative. Left alone, both
    # become bogus once handed to a subprocess with a *different* cwd than
    # whatever this process happened to start in (stream_generate runs spl3
    # with cwd=spl_dir, so a relative public_domains resolves against the
    # SPL.py repo, not this one) — silently pointing at nonexistent paths.
    # create_subprocess_exec raises FileNotFoundError for both an invalid
    # cwd and a missing executable identically, so this was previously
    # misdiagnosed as "spl3 not found" even once spl3's own path was
    # resolved correctly. Anchor relative paths to this repo's root
    # (matching public_domains' own default) rather than trusting cwd.
    @field_validator("spl_dir", "public_domains", mode="after")
    @classmethod
    def _resolve_path(cls, v: Path) -> Path:
        v = v.expanduser()
        if not v.is_absolute():
            v = _REPO_ROOT / v
        return v


settings = Settings()
