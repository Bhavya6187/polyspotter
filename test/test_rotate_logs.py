"""scripts/rotate_logs.sh: size-rotate storybot logs, prune old live_runs."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rotate_logs.sh"
MB = 1024 * 1024


def _age(path: Path, days: int) -> None:
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_rotate_logs_rotates_big_logs_and_prunes_old_runs(tmp_path):
    root = tmp_path / "project"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "rotate_logs.sh")
    logs = root / "storybot" / "logs"
    runs = root / "storybot" / "live_runs"
    logs.mkdir(parents=True)
    runs.mkdir(parents=True)

    with open(logs / "x.log", "wb") as f:
        f.truncate(25 * MB)
    (logs / "x.log.1").write_text("older rotation\n")
    (logs / "small.log").write_text("keep me\n")

    old_dir = runs / "old_run"
    old_dir.mkdir()
    (old_dir / "a.json").write_text("{}")
    old_file = runs / "twitter_pipeline_old.json"
    old_file.write_text("{}")
    new_dir = runs / "new_run"
    new_dir.mkdir()
    new_file = runs / "twitter_pipeline_new.json"
    new_file.write_text("{}")
    for p in (old_dir, old_file):
        _age(p, 40)
    for p in (new_dir, new_file):
        _age(p, 5)

    # Run from an unrelated cwd: the script must locate the root from its own path.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    subprocess.run(["bash", str(root / "scripts" / "rotate_logs.sh")],
                   cwd=elsewhere, check=True)

    assert not (logs / "x.log").exists() or (logs / "x.log").stat().st_size < 20 * MB
    assert (logs / "x.log.1").stat().st_size == 25 * MB
    assert sorted(p.name for p in logs.iterdir()) == ["small.log", "x.log.1"]
    assert (logs / "small.log").read_text() == "keep me\n"
    assert not old_dir.exists() and not old_file.exists()
    assert new_dir.exists() and new_file.exists()
