"""Shared test helpers: where the notebook's engine and results live.

Search order for each file: environment variable, then the repo's notebook/ folder (if the group adds the
submitted notebook there), then the group's notebook working folder given by FM_NOTEBOOK_DIR or by one line in
tests/local_notebook_dir.txt (git-ignored). Missing -> test skipped.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_LOCAL = Path(__file__).with_name("local_notebook_dir.txt")
_GA = Path(os.environ.get("FM_NOTEBOOK_DIR")
           or (_LOCAL.read_text(encoding="utf-8").strip() if _LOCAL.exists() else REPO / "notebook"))


def first_existing(*cands):
    for c in cands:
        if c and Path(c).exists():
            return Path(c)
    return None


def notebook_engine_file():
    return first_existing(os.environ.get("FM_ENGINE"), REPO / "notebook" / "fm_backtest.py", _GA / "engine" / "fm_backtest.py")


def notebook_ipynb():
    env = os.environ.get("FM_NOTEBOOK")
    if env:
        return first_existing(env)
    for d in (REPO / "notebook", _GA):
        if d.exists():
            nbs = sorted(d.glob("*.ipynb"))
            if nbs:
                return nbs[0]
    return None


def results_json():
    return first_existing(os.environ.get("FM_RESULTS"), REPO / "notebook" / "results.json", _GA / "output" / "results.json")


def notebook_inputs_snapshot():
    """Inputs the notebook actually used, if its run exported them (exact reproduction)."""
    return first_existing(os.environ.get("FM_INPUTS"), _GA / "output" / "snapshot_inputs.csv")
