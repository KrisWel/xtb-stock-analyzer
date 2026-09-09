# data/

| File | Committed | Written by |
|------|-----------|------------|
| `instruments.csv` | yes | `xtb-analyzer fetch` — the filtered universe, and the offline fallback for every other command |
| `instruments.meta.json` | yes | `xtb-analyzer fetch` — timestamp, counts, rejection breakdown |
| `raw/all_symbols.json` | **no** (git-ignored) | `xtb-analyzer fetch` — untouched API payload, several MB |

Run `xtb-analyzer fetch` and commit the refreshed `instruments.csv` / `instruments.meta.json`
so the repository always carries a usable universe, including for anyone without XTB credentials.
