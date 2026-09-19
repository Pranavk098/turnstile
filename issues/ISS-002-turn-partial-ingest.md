# ISS-002: Turn-level partial ingest coverage

- Status: accepted
- Source: c2_ingest_partial (`turn_partial 0.95, conf 0.93, act`)
- Problem: one acoustically-incomplete turn poisons the whole call to ABSENT
  (`pipeline.py:71-108`; `adapter.py:160-194`). Good turns are discarded.
- Jev verdict: score measurable turns, ABSENT only the incomplete ones.
- Proposal: turn-level coverage envelope; call rollup keeps honesty labels.
- Accept when: an 8/10-complete fixture scores 8 turns + 2 ABSENT; labels intact;
  pipeline tests green.
