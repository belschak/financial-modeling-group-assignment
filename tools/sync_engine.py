"""Copy the notebook's engine into the app unchanged and print both SHA-256 hashes.

Usage: python tools/sync_engine.py [path/to/notebook/engine/fm_backtest.py]
"""
import hashlib
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from conftest import notebook_engine_file  # noqa: E402

src = Path(sys.argv[1]) if len(sys.argv) > 1 else notebook_engine_file()
if src is None:
    sys.exit("Notebook engine not found; pass its path.")
dst = REPO / "fm_backtest.py"
shutil.copyfile(src, dst)
for p in (src, dst):
    print(hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), p)
