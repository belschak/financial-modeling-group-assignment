"""Refresh the offline snapshot.

  python tools/make_snapshot.py                      # live download with the engine's loader (monthly + daily)
  python tools/make_snapshot.py --from-notebook DIR  # monthly inputs = the notebook run's own output/ (exact
                                                     # consistency), daily file from a live download
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import data_layer as dl  # noqa: E402

data = dl.load_live()
if "--from-notebook" in sys.argv:
    out = Path(sys.argv[sys.argv.index("--from-notebook") + 1])
    shutil.copyfile(out / "snapshot_inputs.csv", dl.SNAP_CSV)
    shutil.copyfile(out / "snapshot_meta.json", dl.SNAP_META)
    dl.save_daily(data)
    print("monthly snapshot = notebook output; daily file from live download", data["retrieved_at"])
else:
    dl.save_snapshot(data)
    print("snapshot written:", dl.describe(data))
