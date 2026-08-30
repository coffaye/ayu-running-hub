"""Version identity shared by Codex, CLI, and future Actions callers."""

ENGINE_VERSION = "0.3.0"
SCHEMA_VERSION = "1.1"
PROMPT_VERSION = "ayu-daily-v7"
RENDERER_VERSION = "ayu-html-canvas-v2"


def runtime_engine_commit() -> str | None:
    """Return an injected commit SHA without baking a moving SHA into code."""

    import os

    value = os.getenv("AYU_ENGINE_COMMIT")
    return value.strip() or None if value else None
