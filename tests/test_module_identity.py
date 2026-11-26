"""The app runs the notebook's module fm_lean.py unchanged, on the notebook's own inputs and results."""
import hashlib
import json

import pytest

import core
from conftest import (EXPECTED_SHA, REPO, notebook_ipynb, notebook_module_file, notebook_results_json,
                      repo_results_json)


def _sha(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_fm_lean_sha_equals_results_json_and_handoff():
    rj = json.loads(repo_results_json().read_text(encoding="utf-8"))
    assert _sha(REPO / "fm_lean.py") == core.SHA == EXPECTED_SHA == rj["meta"]["engine_sha256"]
    assert rj["meta"]["engine_version"] == "lean-2.0"
    assert b"\r\n" not in (REPO / "fm_lean.py").read_bytes()   # LF, as in the notebook folder


def test_fm_lean_identical_to_notebook_folder():
    src = notebook_module_file()
    if src is None:
        pytest.skip("notebook folder not available on this machine")
    assert _sha(src) == core.SHA, "fm_lean.py differs from the notebook's. Run: python tools/sync_engine.py"


def test_fm_lean_identical_to_code_inside_notebook():
    nb = notebook_ipynb()
    if nb is None:
        pytest.skip("notebook (.ipynb) not available on this machine")
    out = []
    for cell in json.loads(nb.read_text(encoding="utf-8"))["cells"]:
        src = "".join(cell.get("source", []))
        first, _, body = src.partition("\n")
        parts = first.split()
        if cell["cell_type"] == "code" and parts[:1] == ["%%writefile"] and parts[-1].endswith("fm_lean.py"):
            out = (out if "-a" in parts else []) + [body]
    if not out:
        pytest.skip(f"{nb.name} has no %%writefile fm_lean.py cells")
    app = (REPO / "fm_lean.py").read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    assert "".join(out).rstrip("\n") == app.rstrip("\n")


def test_repo_copies_equal_current_notebook_output():
    rj = notebook_results_json()
    if rj is None:
        pytest.skip("notebook output not available on this machine")
    for name in ("results.json", "snapshot_inputs.csv", "snapshot_meta.json"):
        assert (REPO / "data" / name).read_bytes() == (rj.parent / name).read_bytes(), (
            f"data/{name} is stale. Run: python tools/make_snapshot.py --from-notebook <notebook output folder>")
