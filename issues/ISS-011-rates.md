# ISS-011: Pricing placeholders + rate-table staleness

- Status: proposed (explorer-flagged, not Jev-voted — needs its own vote)
- Source: schema+pricing explorer D3/D4; schema_pricing vote backed synth only
- Problem: reasoning billed at output rate (UNVERIFIED vs vendor); local Piper priced
  as Cartesia 0.025 (placeholder); single-vendor table dated 2026-08-30 (`rates.yaml`).
- Proposal: dated vendor rows + manifest SHA per METHOD.md:225-228; replace placeholders.
- Accept when: every priced span resolves to a dated row; manifest test green; no silent $0.
