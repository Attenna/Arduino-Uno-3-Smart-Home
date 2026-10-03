"""Create a consistent SQLite snapshot and a private backup of app state."""
from datetime import datetime
from pathlib import Path
import os
import sqlite3
import tarfile

root = Path(__file__).resolve().parents[1]
destination = root.parent / "smart-home-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
destination.mkdir(parents=True, mode=0o700)
os.chmod(destination.parent, 0o700)
with sqlite3.connect(f"file:{root / 'data/smart_home.db'}?mode=ro", uri=True) as source:
    with sqlite3.connect(destination / "smart_home.db") as target:
        source.backup(target)
os.chmod(destination / "smart_home.db", 0o600)
with tarfile.open(destination / "state.tar.gz", "w:gz") as archive:
    for path in (root / "data").rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix not in {".json", ".pkl", ".jpg", ".jpeg", ".png"}:
            continue
        if any("pre-" in part for part in path.relative_to(root).parts):
            continue
        archive.add(path, arcname=str(path.relative_to(root)))
os.chmod(destination / "state.tar.gz", 0o600)
print(destination)
