# CodeGuard Rule Corpus Attribution

The contents of `data/codeguard/rules/` (fetched, not committed -- see
`.gitignore` -- rerun `scripts/fetch_codeguard_rules.py` to regenerate) are
vendored unmodified from
[cosai-oasis/project-codeguard](https://github.com/cosai-oasis/project-codeguard), pinned at
commit `7e19e207bd67abbd3d04ae664441595410df1157`.

Copyright (c) 2026 the Project CodeGuard contributors (Coalition for Secure
AI, an OASIS Open Project). Licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

- Last fetched: 2026-08-17
- Pinned commit: `7e19e207bd67abbd3d04ae664441595410df1157`
- To refresh: bump `PINNED_SHA` in `scripts/fetch_codeguard_rules.py`, rerun it.

This project's own rule-loading and rule-sweep logic
(`src/foundry/codeguard/`) is not part of this vendored content and is
licensed under this repository's own license, not CC BY 4.0.
