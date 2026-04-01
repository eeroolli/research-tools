from __future__ import annotations

import sys
from pathlib import Path


# Ensure repository root is on sys.path so imports like `shared_tools.*` work
# consistently across different pytest invocation styles/environments.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

