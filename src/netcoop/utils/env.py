"""Environment variable and .env loader for NetCoop AI."""

import os
from pathlib import Path


def load_dotenv(dotenv_path: Path | str | None = None) -> bool:
    """Loads environment variables from a .env file into os.environ.

    Does not overwrite existing environment variables.
    Returns True if a .env file was found and processed, False otherwise.
    """
    path = Path(dotenv_path) if dotenv_path else Path.cwd() / ".env"
    if not path.is_file():
        # Fallback to repository root relative to this file
        repo_root = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        if repo_root.is_file():
            path = repo_root
        else:
            return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
        return True
    except Exception:
        return False
