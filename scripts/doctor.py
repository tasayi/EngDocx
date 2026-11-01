#!/usr/bin/env python3
"""EngDoc CLI Diagnostic Script."""

import sys
from pathlib import Path

# Add src to python path if running standalone
root_dir = Path(__file__).resolve().parent.parent
src_dir = root_dir / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from engdoc.core.diagnostics import main  # noqa: E402

if __name__ == "__main__":
    main()
