"""EngDoc Core Configuration."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    APP_NAME: str = "EngDoc"
    VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"

    # Base paths
    ROOT_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
    SRC_DIR: Path = Path(__file__).resolve().parent.parent
    FRONTEND_DIR: Path = ROOT_DIR / "frontend"
    TEMPLATES_DIR: Path = ROOT_DIR / "templates"

    # Environment & Host
    HOST: str = os.getenv("ENGDOC_HOST", "127.0.0.1")
    PORT: int = int(os.getenv("ENGDOC_PORT", "8000"))
    DEBUG: bool = os.getenv("ENGDOC_DEBUG", "false").lower() in ("true", "1")
    IS_WINDOWS: bool = sys.platform == "win32"

settings = Settings()
