"""Copy the notebook's module fm_lean.py into the app unchanged and print both SHA-256 hashes.

Usage: python tools/sync_engine.py [path/to/02-Notebook/fm_lean.py]
"""
import hashlib
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from conftest import notebook_module_file  # noqa: E402

src = Path(sys.argv[1]) if len(sys.argv) > 1 else notebook_module_file()
if src is None:
    sys.exit("Notebook module fm_lean.py not found; pass its path.")
dst = REPO / "fm_lean.py"
shutil.copyfile(src, dst)
for p in (src, dst):
    print(hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), p)
