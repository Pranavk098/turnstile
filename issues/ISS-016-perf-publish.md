# ISS-016: Perf baseline + publish (bench, pip, deploy)

- Status: future
- Source: Track C future-item 8; ROADMAP "fast unmeasured, invisible, not installable"
- Problem: no benchmark, no installable package, demo-only visibility; free-tier cold
  start 22.4s vs 5s budget.
- Proposal: pytest-benchmark + PERF.md + Render/HF deploy + pip-installable sdist ($0 path
  first); optimize and observe on measured evidence only.
- Accept when: benchmark runs in CI; `pip install` works; deploy + cold-start state documented.
