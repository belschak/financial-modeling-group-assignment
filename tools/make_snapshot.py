"""Refresh the offline snapshot.

  python tools/make_snapshot.py --from-notebook DIR   # copy the notebook run's output/ (snapshot + results.json):
                                                      # offline defaults then equal the notebook exactly
  python tools/make_snapshot.py                       # live download with fm_lean.load_data instead
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import data_layer as dl  # noqa: E402

if "--from-notebook" in sys.argv:
    out = Path(sys.argv[sys.argv.index("--from-notebook") + 1])
    for name in ("snapshot_inputs.csv", "snapshot_meta.json", "results.json"):
        shutil.copyfile(out / name, dl.DATA_DIR / name)
    print("snapshot + results.json = notebook output", dl.load_snapshot()["retrieved_at"])
else:
    d = dl.load_live()
    dl.save_snapshot(d)
    print("snapshot written from a live download", d["retrieved_at"])
