"""Download live inputs with the engine's own loader and store them as the offline fallback snapshot.

Usage: python tools/make_snapshot.py   (needs internet; writes data/snapshot_inputs.csv + data/snapshot_meta.json)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import data_layer as dl  # noqa: E402

data = dl.load_live()
dl.save_snapshot(data)
print("snapshot written:", dl.describe(data))
