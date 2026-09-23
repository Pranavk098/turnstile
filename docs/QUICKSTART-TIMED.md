# QUICKSTART — timed dry run ("stranger < 10 min", Day-6 P1-5)

Dry run 2026-09-20, Windows 11, clean-checkout-equivalent (`uv sync` from lock,
full suite, `build_data.py` = `make demo`'s report step, serve + open + POST).
Box quirk (environmental, not product): AppControl blocks bare `uvicorn` /
`pytest` shims → use `uv run python -m uvicorn` / `uv run python -m pytest`.

| # | Step (exact command) | Wall | Proves |
|---|---|---|---|
| 1 | `uv sync` | **1.8 s** | install from lock |
| 2 | `uv run python -m pytest -q` | **91.2 s** | 1258 passed, 4 skipped, **1 pre-existing FAIL** (`tests/test_readme_count.py` — README suite-count drift from concurrent track edits; dirty tree, not this track; needs Track B/human) |
| 3 | `uv run python packages/dashboard/build_data.py` | **1.6 s** | dashboard builds; regen byte-stable (`git status` clean on `sample/`); barge-in headline 4.07% @ 0.15, n=150 |
| 4 | `uv run python -m uvicorn turnstile_service.app:app --port 8000` then open `http://localhost:8000/home.html` | boot ~22 s (uv cold import; uvicorn ready), `GET /home.html` 200 in **0.08 s** | guided tour serves; barge-in panel present; quality-beside-cost in `index.html` fleet cells + hero-quality panel (tiers verbatim) |
| 5 | `POST /api/evaluate` with the `docs/INGEST.md` doc-example (`packages/service/src/turnstile_service/example_call.json`) | cold **0.10 s** (200, 8236 B), warm hit **0.003 s**, byte-identical | paste-own-call instant report: cost $0.00523, verdict RESOLVED, quality `pass/measured` |

**Total ≈ 117 s (~2 min) < 10 min — GREEN** (even counting the 22 s cold boot
once, not twice).

Stranger quickstart (the path above, copy-paste):

```bash
uv sync
uv run python -m pytest -q            # expect green on a clean tree; see note on step 2
uv run python packages/dashboard/build_data.py
uv run python -m uvicorn turnstile_service.app:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/home.html (home → fleet → call → ingest)
curl -X POST http://127.0.0.1:8000/api/evaluate -H "Content-Type: application/json" \
  --data-binary @packages/service/src/turnstile_service/example_call.json
```
