"""Central configuration, read from environment variables (see .env.example)."""
import os
from pathlib import Path


def _load_dotenv() -> None:
    """Read the repo's .env for local dev (docker compose passes it in itself). Real env vars win."""
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default   # an empty value means "use the default"


ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY")
OPENROUTER_URL = _env("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_REASONING = _env("OPENROUTER_REASONING", "0") == "1"

# "openrouter" | "anthropic" | "" (offline). Defaults to whichever key is set, OpenRouter first.
LLM_PROVIDER = _env("LLM_PROVIDER") or ("openrouter" if OPENROUTER_API_KEY else "anthropic" if ANTHROPIC_API_KEY else "")

if LLM_PROVIDER == "openrouter":
    HELPER_MODEL = _env("HELPER_MODEL", "nvidia/nemotron-3.5-lightning:free")
    JUDGE_MODEL = _env("JUDGE_MODEL", "nvidia/nemotron-3.5-lightning:free")
else:
    HELPER_MODEL = _env("HELPER_MODEL", "claude-haiku-4-5-20251001")   # fast, cheap: live hints
    JUDGE_MODEL = _env("JUDGE_MODEL", "claude-sonnet-5-5")              # stronger: final review

REDIS_URL = _env("REDIS_URL")                 # empty -> in-memory store only

SANDBOX = _env("SANDBOX", "local")            # "local" | "judge0"
JUDGE0_URL = _env("JUDGE0_URL", "http://localhost:2358")
JUDGE0_TOKEN = _env("JUDGE0_TOKEN")
JUDGE0_PYTHON_ID = int(_env("JUDGE0_PYTHON_ID", "71"))

SANDBOX_MEMORY_MB = int(_env("SANDBOX_MEMORY_MB", "512"))
SANDBOX_MAX_SECONDS = float(_env("SANDBOX_MAX_SECONDS", "20"))

IDLE_CHECK_SECONDS = 5
