"""The app must run the notebook's engine code unchanged (brief: app calculations consistent with the notebook)."""
import json

import pytest

from conftest import REPO, notebook_engine_file, notebook_ipynb

APP_ENGINE = REPO / "fm_backtest.py"


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def test_engine_file_identical_to_notebook_engine_file():
    nb_engine = notebook_engine_file()
    if nb_engine is None:
        pytest.skip("notebook engine file not available on this machine")
    assert _norm(APP_ENGINE.read_bytes()) == _norm(nb_engine.read_bytes()), (
        f"fm_backtest.py differs from {nb_engine}. Run: python tools/sync_engine.py")


def _engine_from_notebook(path) -> str | None:
    """Rebuild fm_backtest.py from the notebook's %%writefile cells (with -a for appends)."""
    nb = json.loads(path.read_text(encoding="utf-8"))
    out, found = [], False
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        first, _, body = src.partition("\n")
        parts = first.split()
        if parts and parts[0] == "%%writefile" and parts[-1].endswith("fm_backtest.py"):
            if "-a" not in parts:
                out = []
            out.append(body)
            found = True
    return "".join(out) if found else None


def test_engine_identical_to_code_inside_notebook():
    nb = notebook_ipynb()
    if nb is None:
        pytest.skip("notebook (.ipynb) not available on this machine")
    code = _engine_from_notebook(nb)
    if code is None:
        pytest.skip(f"{nb.name} has no %%writefile fm_backtest.py cells")
    app = _norm(APP_ENGINE.read_bytes()).decode("utf-8")
    assert code.rstrip("\n") == app.rstrip("\n"), f"engine inside {nb.name} differs from the app's fm_backtest.py"
