"""Shared test helpers: where the notebook's module and results live.

data/results.json is the notebook run's own results file, copied by tools/make_snapshot.py --from-notebook, so the
consistency tests also run in GitHub Actions. On the group's machine the notebook folder (FM_NOTEBOOK_DIR or one line
in tests/local_notebook_dir.txt, git-ignored) adds the checks against the live notebook files. Missing -> skipped.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_LOCAL = Path(__file__).with_name("local_notebook_dir.txt")
_NB = os.environ.get("FM_NOTEBOOK_DIR") or (_LOCAL.read_text(encoding="utf-8").strip() if _LOCAL.exists() else "")
NB = Path(_NB) if _NB else None

EXPECTED_SHA = "a75c318a096da7c61624d16748e38f08ea166399cc0fc28a93feed9fa8a1da83"  # fm_lean.py lean-2.0 (LF)


def _nb(*parts):
    p = NB.joinpath(*parts) if NB else None
    return p if p is not None and p.exists() else None


def notebook_module_file():
    return _nb("fm_lean.py")


def notebook_ipynb():
    """The notebook built from the current module: build/ while the new version waits for its final Colab run."""
    if NB is None or not NB.exists():
        return None
    for folder in (NB / "build", NB):
        nbs = sorted(folder.glob("*.ipynb"))
        if nbs:
            return nbs[0]
    return None


def notebook_results_json():
    return _nb("build", "output", "results.json") or _nb("output", "results.json")


def repo_results_json():
    p = REPO / "data" / "results.json"
    return p if p.exists() else None
