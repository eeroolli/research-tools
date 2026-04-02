from __future__ import annotations

import sys
from pathlib import Path


# Ensure repository root is on sys.path so imports like `shared_tools.*` work
# consistently across different pytest invocation styles/environments.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# `handle_item_selected_pages` and other CLI modules live under scripts/
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

