"""Fetch the CodeGuard rule corpus into data/codeguard/rules.

Vendors `sources/rules/{core,owasp}` from cosai-oasis/project-codeguard at a
pinned commit, so the Detector's rule-sweep depends on a known corpus rather
than a moving upstream target. To refresh, bump PINNED_SHA below and rerun --
that is a deliberate decision, not something that happens on every install.

Rule content is reproduced under CC BY 4.0 from
https://github.com/cosai-oasis/project-codeguard. See the generated
data/codeguard/ATTRIBUTION.md for the full notice.

Usage:
    python scripts/fetch_codeguard_rules.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_URL = "https://github.com/cosai-oasis/project-codeguard.git"
PINNED_SHA = "7e19e207bd67abbd3d04ae664441595410df1157"

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "codeguard" / "rules"
ATTRIBUTION = ROOT / "data" / "codeguard" / "ATTRIBUTION.md"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        print(f"Cloning {REPO_URL} @ {PINNED_SHA[:12]} ...")
        subprocess.run(["git", "clone", "--quiet", REPO_URL, str(tmp_path)], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "--quiet", PINNED_SHA], check=True
        )

        src_rules = tmp_path / "sources" / "rules"
        if not src_rules.exists():
            sys.exit(
                f"sources/rules not found at pinned commit {PINNED_SHA} "
                "-- upstream layout changed, update this script"
            )

        if DEST.exists():
            shutil.rmtree(DEST)
        DEST.mkdir(parents=True)

        total = 0
        for category_dir in sorted(src_rules.iterdir()):
            if not category_dir.is_dir():
                continue
            out_dir = DEST / category_dir.name
            shutil.copytree(category_dir, out_dir)
            count = len(list(out_dir.glob("*.md")))
            total += count
            print(f"  {category_dir.name}: {count} rules")

        print(f"Vendored {total} rule files into {DEST.relative_to(ROOT)}")

    ATTRIBUTION.parent.mkdir(parents=True, exist_ok=True)
    ATTRIBUTION.write_text(
        f"""# CodeGuard Rule Corpus Attribution

The contents of `data/codeguard/rules/` (fetched, not committed -- see
`.gitignore` -- rerun `scripts/fetch_codeguard_rules.py` to regenerate) are
vendored unmodified from
[cosai-oasis/project-codeguard]({REPO_URL.removesuffix('.git')}), pinned at
commit `{PINNED_SHA}`.

Copyright (c) 2026 the Project CodeGuard contributors (Coalition for Secure
AI, an OASIS Open Project). Licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

- Last fetched: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
- Pinned commit: `{PINNED_SHA}`
- To refresh: bump `PINNED_SHA` in `scripts/fetch_codeguard_rules.py`, rerun it.

This project's own rule-loading and rule-sweep logic
(`src/foundry/codeguard/`) is not part of this vendored content and is
licensed under this repository's own license, not CC BY 4.0.
"""
    )
    print(f"Wrote attribution to {ATTRIBUTION.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
