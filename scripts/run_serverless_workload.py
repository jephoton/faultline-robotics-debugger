"""Image entrypoint: run one bounded Faultline workload from an injected JSON file."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from robot_debug.job_entry import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
