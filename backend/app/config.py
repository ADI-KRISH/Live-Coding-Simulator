"""Central configuration, read from environment variables (see .env.example)."""
import os


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
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
