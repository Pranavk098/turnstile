# Quality & evaluation

Every per-call report carries a `quality` block beside cost. The rubric —
which dimensions are measured rules, which stay calibration-pending
no-ops — is defined in [METHOD.md](METHOD.md) ("Quality beside cost")
and bounded in [Limitations](LIMITATIONS.md).

No score ships without a passing calibration (hand labels, agreement,
ECE reported). Pending reads as pending, never as 0 or fail.
