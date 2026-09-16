"""Retell call-export adapter: one Retell call object -> ``IngestCall``.

Pure data transformation ($0: no provider-API calls, no model calls, no
network imports anywhere in this module). The Retell field names below are
authored against Retell's published Get Call schema (re-verified 2026-09-15,
OpenAPI ``x-retell-spec-revision: 2026-09-14-b240eb0``) and cited in
``docs/INGEST.md``:

* Call object: ``call_id``, ``agent_id``, ``agent_name``, ``agent_version``
  (**int**), ``call_status`` (``registered | not_connected | ongoing | ended
  | error``), ``call_type`` (``web_call | phone_call``; phone adds
  ``direction`` (``inbound | outbound``), ``from_number``, ``to_number``),
  ``start_timestamp`` / ``end_timestamp`` (**epoch ms ints**) /
  ``duration_ms`` (``https://docs.retellai.com/api-references/get-call``).
* Timeline: ``transcript_with_tool_calls`` (preferred) or
  ``transcript_object`` -- ``Utterance`` (``role`` agent | user |
  transfer_target, ``content``, ``words[{word, start, end}]``),
  ``tool_call_invocation`` (``tool_call_id``, ``name``, ``arguments``
  (stringified JSON)) and ``tool_call_result`` (``tool_call_id``,
  ``content``, ``successful?``), ``node_transition`` (informational),
  ``dtmf`` / ``sms`` / ``injected`` (not spoken turns).
* Outcome: ``disconnection_reason`` vocabulary
  (``https://docs.retellai.com/reliability/debug-call-disconnect``).
* Totals: ``llm_token_usage`` (``values[]``, ``average``, ``num_requests`` --
  combined per-request counts with NO prompt/completion split);
  ``call_cost`` / ``latency`` are billing/diagnostic summaries, never token
  sources (``https://docs.retellai.com/reliability/check-actual-latency``).

Honesty rules (Track A section 3.5, all load-bearing):

* ``decision_kind`` is NEVER read from the export -- Retell does not emit it.
  Every adapted LLM turn is inferred by the documented rules in
  :func:`_infer_decision_kind` and flagged via
  :func:`inferred_decision_turns` / :func:`provider_info`. The pipeline marks
  D1 ABSENT for fully-inferred calls and drops any residual D1 finding on an
  inferred turn, so an inferred label can never masquerade as an
  agent-emitted one in a headline number.
* Per-turn LLM tokens are NOT emitted by Retell either -- only the
  call-level ``llm_token_usage`` combined total, which carries NO
  prompt/completion split. The combined total is distributed evenly across
  the call's LLM turns as ``input_tokens`` with ``output_tokens`` 0 (exact
  sum preserved in ``input``; per-turn attribution approximate and flagged;
  output cost unmeasured, not zero). Even (not text-proportional) splits
  deliberately: a text-proportional split would fabricate a token slope D2
  could misread. When ``llm_token_usage`` is absent (custom LLM / realtime
  API / no LLM call) AND LLM turns exist, adaptation raises
  :class:`IngestError` instead of inventing tokens. ``latency`` /
  ``call_cost`` are never token sources.
* TTS char counts are not emitted by Retell at all, so adapted ``tts``
  blocks carry text + timing with NO char counts. The existing adapter then
  emits no tts/playback spans and the pipeline reports D6/D7/D8 ABSENT --
  the honest result. Never ``len(text)``.
* Tool ``kind`` has no honest derivation from the export alone, so it is
  inferred from documented name rules (:data:`TOOL_KIND_RULES`) with an
  explicit ``tool_kinds`` override for ground truth, and an unknown name
  raises :class:`IngestError` naming the tool -- never a silent default.
  ``effect`` resolves ``unknown`` when the export leaves it ambiguous (the
  verdict layer caps confidence on ``unknown`` rather than fabricating).
* LLM identity: Retell names no model (there is no ``assistant.model``
   equivalent), so the caller MUST supply ``llm_identity=(system, model)``
   with a ``pricing/rates.yaml``-resolvable model -- or the export itself
   carries hand-authored ground truth as a top-level ``agent_model``
   ``{system, model}`` key (synthetic fixtures only; a real Get Call export
   never has it). Explicit ``llm_identity`` wins over the embedded key.
   When the call has agent turns and neither was supplied, adaptation raises
   :class:`IngestError` naming the gap instead of defaulting to a tier the
   export never named. The provenance note records the priced identity.
* Telephony: Retell names no PSTN provider (``telephony_identifier`` carries
  at most a tracking SID), so ``phone_call`` legs use the explicit
  ``telephony_provider`` parameter (default ``"twilio"``). The default is an
  ASSUMPTION, not a measurement: it is documented here, in the provenance
  note, and in ``docs/INGEST.md``, and a missing
  ``<provider>/pstn_<direction>`` rate key still fails loudly at load.
  ``web_call`` carries no phone leg (D8 is then honestly ABSENT via the
  existing envelope).
* Timeline skips (documented, tested): ``dtmf`` / ``sms`` / ``injected``
  entries are not spoken turns and are skipped; ``node_transition`` entries
  are conversation-flow bookkeeping (which agent node ran), informational
  only, never a turn. Word ``start``/``end`` are relative audio seconds
  that Retell documents as approximate ("not guaranteed to be accurate");
  an utterance without usable word timings is placed by evenly dividing the
  call duration in document order, and the provenance note says so.
* Anything else unmappable raises :class:`IngestError` with the source
  field path (unmapped ``disconnection_reason``, non-``ended``
  ``call_status``, unknown entry role, missing ``llm_token_usage`` when LLM
  turns exist, contradictory tool results).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from turnstile_ingest.adapter import IngestError
from turnstile_ingest.model import IngestCall

PROVIDER = "retell"
#: Month the Retell Get Call field names were verified against the published
#: docs (OpenAPI x-retell-spec-revision 2026-09-14-b240eb0). Bump when
#: re-verifying against a newer export version.
EXPORT_VERSION = "2026-09"
#: Retell spec revision the field names above were verified against.
SPEC_REVISION = "2026-09-14-b240eb0"

# --------------------------------------------------------------------------- #
# disconnection_reason -> EndReason                                             #
# --------------------------------------------------------------------------- #

#: Exact Retell disconnection-reason codes with a deterministic Turnstile
#: mapping. Sources: https://docs.retellai.com/api-references/get-call
#: (DisconnectionReason enum) and
#: https://docs.retellai.com/reliability/debug-call-disconnect (cause table).
#: user_hangup = the caller hung up; agent_hangup = the agent hung up;
#: call_transfer / transfer_bridged = the call left to a transfer target
#: (the escalation path); inactivity / max_duration_reached = timeouts.
_END_REASON_EXACT = {
    "user_hangup": "caller_hangup",
    "agent_hangup": "agent_hangup",
    "call_transfer": "escalated",
    "transfer_bridged": "escalated",
    "inactivity": "timeout",
    "max_duration_reached": "timeout",
}

#: Every other code in the documented enum: voicemail/IVR landings, dial and
#: SIP failures, payment/concurrency blocks, transfer failures, takeovers,
#: and all error_* / timeout registrations. None of these is a
#: hangup/timeout/escalation -- the conversation did not end normally.
_ERROR_EXACT = frozenset({
    "voicemail_reached",
    "ivr_reached",
    "concurrency_limit_reached",
    "no_concurrency_fallback",
    "no_valid_payment",
    "scam_detected",
    "dial_busy",
    "dial_failed",
    "dial_no_answer",
    "invalid_destination",
    "telephony_provider_permission_denied",
    "telephony_provider_unavailable",
    "sip_routing_error",
    "marked_as_spam",
    "user_declined",
    "error_llm_websocket_open",
    "error_llm_websocket_lost_connection",
    "error_llm_websocket_runtime",
    "error_llm_websocket_corrupt_payload",
    "error_no_audio_received",
    "error_asr",
    "error_retell",
    "error_unknown",
    "error_user_not_joined",
    "registered_call_timeout",
    "transfer_cancelled",
    "manual_stopped",
    "call_take_over",
})


def map_end_reason(value: Any, *, path: str = "disconnection_reason") -> str:
    """Map one Retell ``disconnection_reason`` code to an ``EndReason`` value.

    Raises :class:`IngestError` naming ``path`` and the offending value when
    the code matches neither the exact table nor the documented error set --
    a new Retell code must map explicitly, never silently default.
    """
    if isinstance(value, str) and value in _END_REASON_EXACT:
        return _END_REASON_EXACT[value]
    if isinstance(value, str) and value in _ERROR_EXACT:
        return "error"
    raise IngestError(
        f"{path} {value!r}: unmapped Retell disconnection_reason -- add an "
        "explicit mapping in turnstile_ingest.providers.retell.map_end_reason "
        "(caller_hangup | agent_hangup | escalated | timeout | error)"
    )


# --------------------------------------------------------------------------- #
# Tool kind / effect                                                           #
# --------------------------------------------------------------------------- #

#: Name-substring rules mapping a Retell tool (function) name to a Turnstile
#: ``ToolKind``. Same shape and order contract as the Vapi adapter's table;
#: order is load-bearing (first match wins): handoff signals beat everything
#: (a transfer is an escalation whatever else the name says), then explicit
#: retrieval signals, then lookup verbs (reads), then mutation verbs
#: (world-changing). Anything unmatched raises -- pass ``tool_kinds`` with
#: ground truth instead of letting the adapter guess.
TOOL_KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("handoff", ("transfer", "handoff", "forward", "escalat")),
    ("retrieval", ("knowledge", "kb_", "_kb", "faq", "rag", "docs", "retriev")),
    ("lookup", ("lookup", "look_up", "get_", "_get", "fetch", "check", "search",
                "find", "verif", "list_", "_list", "query", "status", "track")),
    ("mutation", ("book", "cancel", "reschedul", "schedul", "pay", "refund",
                   "updat", "creat", "delet", "submit", "order", "adjust",
                   "modif", "change", "send", "issue", "appl", "process",
                   "complet", "confirm")),
)


def infer_tool_kind(tool_name: str, *, tool_kinds: dict[str, str] | None = None,
                    path: str = "tool") -> str:
    """Resolve a Retell tool name to a ``ToolKind`` value.

    ``tool_kinds`` (``{tool_name: kind}``) is caller-supplied ground truth and
    wins over the name rules. Without an override, the first matching
    :data:`TOOL_KIND_RULES` entry wins; no match raises :class:`IngestError`
    naming the tool.
    """
    if tool_kinds and tool_name in tool_kinds:
        kind = tool_kinds[tool_name]
        if kind not in ("retrieval", "mutation", "lookup", "handoff"):
            raise IngestError(
                f"{path} {tool_name!r}: tool_kinds override {kind!r} is not a "
                "ToolKind (retrieval | mutation | lookup | handoff)"
            )
        return kind
    lowered = tool_name.lower()
    for kind, hints in TOOL_KIND_RULES:
        if any(h in lowered for h in hints):
            return kind
    raise IngestError(
        f"{path} {tool_name!r}: cannot map Retell tool name to a ToolKind "
        "-- pass ground truth via from_retell(..., tool_kinds="
        f'{{"{tool_name}": "<retrieval|mutation|lookup|handoff>"}})'
    )


_PENDING_MARKERS = ("pending", "queued", "on hold", "on-hold", "in progress",
                    "may take a moment", "submitted", "processing")
_FAILURE_MARKERS = ("fail", "error", "reject", "unable", "could not",
                    "couldn't", "declined", "cancelled by", "canceled by",
                    "timed out", "timeout")


def resolve_tool_effect(kind: str, *, content: Any | None, successful: Any | None,
                        has_result: bool, tool_name: str,
                        path: str = "tool") -> tuple[str, str]:
    """Resolve ``(effect, status)`` for one Retell tool call.

    * ``lookup`` / ``retrieval`` are reads: ``effect`` is always ``none``
      (the schema forbids anything else); ``status`` is ``error`` only when
      the export marks ``successful`` false.
    * ``mutation`` / ``handoff`` with ``successful is False`` or an explicit
      ``error`` payload in the content: ``(rejected, error)``.
    * ``mutation`` / ``handoff`` with a result: ``pending`` on pending
      markers, ``rejected`` on failure markers, else ``committed`` (a bare
      success result is a completion).
    * ``mutation`` / ``handoff`` with neither: ``(unknown, ok)`` -- genuinely
      ambiguous; the verdict layer caps confidence instead of fabricating.
    * Content carrying both ``result`` and ``error`` keys: contradictory --
      :class:`IngestError` (loud, not a guess).
    """
    if kind in ("lookup", "retrieval"):
        return "none", ("error" if successful is False else "ok")
    parsed: dict[str, Any] | None = None
    if has_result and isinstance(content, str) and content.strip():
        try:
            candidate = json.loads(content)
        except json.JSONDecodeError:
            candidate = None
        if isinstance(candidate, dict):
            parsed = candidate
    if isinstance(parsed, dict) and "result" in parsed and "error" in parsed:
        raise IngestError(
            f"{path} {tool_name!r}: contradictory tool result -- content "
            "carries both 'result' and 'error'; cannot resolve effect"
        )
    if successful is False:
        return "rejected", "error"
    if isinstance(parsed, dict) and "error" in parsed:
        return "rejected", "error"
    if not has_result or content is None or (isinstance(content, str) and not content.strip()):
        return "unknown", "ok"
    text = content if isinstance(content, str) else json.dumps(content, sort_keys=True, default=str)
    lowered = text.lower()
    if any(m in lowered for m in _PENDING_MARKERS):
        return "pending", "ok"
    if any(m in lowered for m in _FAILURE_MARKERS):
        return "rejected", "ok"
    return "committed", "ok"


# --------------------------------------------------------------------------- #
# Small parsing helpers                                                        #
# --------------------------------------------------------------------------- #

_CALLER_ROLES = frozenset({"user", "transfer_target"})
_SKIP_ROLES = frozenset({"dtmf", "sms", "injected"})
_INFO_ROLES = frozenset({"node_transition"})


def _parse_epoch_ms(value: Any, *, path: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise IngestError(f"{path}: expected epoch milliseconds (non-negative number), got {value!r}")
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise IngestError(f"{path} {value!r}: not a representable epoch-millisecond timestamp") from None


def _slugify(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return slug or "unknown"


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_total(total: int, n: int, *, path: str) -> list[int]:
    """Split a call-level token total evenly across ``n`` turns.

    Exact-sum (``sum == total``; the remainder lands on the earliest turns),
    so the call's priced cost still matches the export's measured totals.
    """
    if n <= 0:
        return []
    if total < 0:
        raise IngestError(f"{path}: token total must be >= 0, got {total!r}")
    base, remainder = divmod(total, n)
    return [base + (1 if i < remainder else 0) for i in range(n)]


def _require_int(value: Any, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IngestError(f"{path}: expected a number, got {value!r}")
    if int(value) != value or value < 0:
        raise IngestError(f"{path}: expected a non-negative integer, got {value!r}")
    return int(value)


# --------------------------------------------------------------------------- #
# Timeline extraction                                                          #
# --------------------------------------------------------------------------- #

def _timeline(call_obj: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """The call's timeline entries plus the source path they came from.

    ``transcript_with_tool_calls`` (non-empty) is preferred; else
    ``transcript_object``. Raises :class:`IngestError` when neither holds a
    non-empty list.
    """
    twtc = call_obj.get("transcript_with_tool_calls")
    if isinstance(twtc, list) and twtc:
        path = "transcript_with_tool_calls"
        entries: Any = twtc
    else:
        tobj = call_obj.get("transcript_object")
        if not isinstance(tobj, list) or not tobj:
            raise IngestError(
                "transcript_with_tool_calls/transcript_object: Retell export "
                "carries no conversation timeline (neither "
                "'transcript_with_tool_calls' nor 'transcript_object' holds "
                "a non-empty list)"
            )
        path = "transcript_object"
        entries = tobj
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise IngestError(f"{path}[{index}]: expected an entry object, got {entry!r}")
    return entries, path


def _normalize_entry(entry: dict[str, Any], index: int, *, path: str) -> tuple[str, dict[str, Any]]:
    """Normalize one timeline entry to a ``(kind, node)`` pair.

    Kinds: ``user`` | ``transfer`` (transfer_target speech, caller-side) |
    ``assistant`` | ``invocation`` | ``result`` | ``skip`` (dtmf/sms/
    injected -- not spoken turns) | ``info`` (node_transition --
    informational bookkeeping, never a turn). Raises :class:`IngestError`
    on a missing or unknown role -- a new Retell entry kind must map
    explicitly, never be silently dropped.
    """
    node = entry
    if "role" not in entry:
        raise IngestError(
            f"{path}[{index}]: entry has no 'role' -- map it explicitly "
            "in turnstile_ingest.providers.retell._normalize_entry"
        )
    role = str(node.get("role") or "").lower()
    if role == "user":
        return "user", node
    if role == "transfer_target":
        # A third party (transfer destination) speaking post-handoff. The
        # ingest format only has caller/agent sides; their speech is NOT the
        # agent's, so it rides caller-side as ASR (never as an LLM decision).
        return "transfer", node
    if role == "agent":
        return "assistant", node
    if role == "tool_call_invocation":
        return "invocation", node
    if role == "tool_call_result":
        return "result", node
    if role in _SKIP_ROLES:
        return "skip", node
    if role in _INFO_ROLES:
        return "info", node
    raise IngestError(
        f"{path}[{index}]: unknown entry role {node.get('role')!r} "
        "-- map it explicitly in turnstile_ingest.providers.retell._normalize_entry"
    )


def _invocation_in(node: dict[str, Any], index: int, *, path: str) -> dict[str, Any]:
    """Extract ``{id, name, arguments}`` from a tool_call_invocation node.

    ``arguments`` is a stringified JSON object per the schema; an absent or
    blank value means "no arguments" (``{}``). Anything else unparseable
    raises :class:`IngestError` naming the entry.
    """
    call_id = node.get("tool_call_id")
    name = node.get("name")
    if not call_id or not name:
        raise IngestError(
            f"{path}[{index}]: tool invocation needs 'tool_call_id' and 'name'"
        )
    args = node.get("arguments", {})
    if isinstance(args, str):
        if not args.strip():
            args = {}
        else:
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                raise IngestError(
                    f"{path}[{index}]: tool invocation 'arguments' is not "
                    "an object or JSON string"
                ) from None
    if not isinstance(args, dict):
        raise IngestError(
            f"{path}[{index}]: tool invocation 'arguments' must be an object"
        )
    return {"id": str(call_id), "name": str(name), "arguments": args}


def _utterance_window(node: dict[str, Any], *, call_duration_ms: int,
                      slot: int, n_slots: int) -> tuple[int, int, bool]:
    """(start_ms, duration_ms, used_fallback) call-relative wall times.

    Word ``start``/``end`` are relative audio seconds (documented
    approximation); the utterance window runs first-word-start to
    last-word-end, clamped to >= 0. An utterance without usable word timings
    is placed by evenly dividing the call duration in document order
    (``used_fallback`` True -- the provenance note says so).
    """
    words = node.get("words")
    if isinstance(words, list) and words:
        first = words[0] if isinstance(words[0], dict) else {}
        last = words[-1] if isinstance(words[-1], dict) else {}
        start = _as_number(first.get("start"))
        end = _as_number(last.get("end"))
        if start is not None and end is not None:
            start_ms = int(round(max(0.0, start) * 1000))
            end_ms = int(round(max(0.0, end) * 1000))
            return start_ms, max(0, end_ms - start_ms), False
    total = max(0, call_duration_ms)
    if n_slots <= 0:
        return 0, 0, True
    start_ms = (slot * total) // n_slots
    end_ms = ((slot + 1) * total) // n_slots
    return start_ms, max(0, end_ms - start_ms), True


# --------------------------------------------------------------------------- #
# decision_kind inference                                                      #
# --------------------------------------------------------------------------- #

def _infer_decision_kind(turn_index: int, *, is_first_llm_turn: bool,
                         has_mutating_tool: bool) -> str:
    """Infer ``decision_kind`` where deterministically safe (documented rule):

    * a turn whose agent message triggers a mutation/handoff tool ->
      ``tool_select`` (the turn IS a tool-selection step);
    * the call's first LLM turn -> ``route`` (the opening exchange decides the
      intent; Retell exposes no candidate set, so "route-like candidates" is
      read as "the opening turn");
    * otherwise -> ``compose`` (a reply; the only claim is that text was
      composed).

    ``slot_fill`` / ``escalate_check`` are NEVER inferred -- no safe rule
    exists, and both are D1-relevant. Every returned kind is flagged
    ``inferred`` in provenance regardless.
    """
    if has_mutating_tool:
        return "tool_select"
    if is_first_llm_turn:
        return "route"
    return "compose"


# --------------------------------------------------------------------------- #
# from_retell                                                                  #
# --------------------------------------------------------------------------- #

def _scenario(call_obj: dict[str, Any]) -> str:
    name = call_obj.get("agent_name")
    if name:
        return _slugify(name)
    return "unknown"


def _agent_version(call_obj: dict[str, Any]) -> str:
    agent_id = call_obj.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        raise IngestError(
            f"agent_id {agent_id!r}: Retell export names no agent id "
            "(expected a non-empty 'agent_id' string)"
        )
    version = call_obj.get("agent_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise IngestError(
            f"agent_version {version!r}: Retell emits the agent version as "
            "an int (expected integer 'agent_version')"
        )
    return f"retell/{agent_id}.v{version}"


def _llm_identity(call_obj: dict[str, Any],
                   llm_identity: tuple[str, str] | list[str] | None) -> tuple[str, str, str]:
    """(system, model, source) for the call's LLM -- caller-supplied ground truth.

    Retell names no model, so there is no honest default: precedence is the
    explicit ``llm_identity`` pair, then the export's own ``agent_model``
    ``{system, model}`` fixture key (hand-authored ground truth for synthetic
    samples -- a real Get Call export never carries it), else a loud
    :class:`IngestError`. Either way the identity prices against a tier the
    caller named, never one the adapter invented; ``source`` records which.
    """
    source = "explicit llm_identity"
    if llm_identity is None:
        embedded = call_obj.get("agent_model")
        if isinstance(embedded, dict):
            llm_identity = (embedded.get("system"), embedded.get("model"))
            source = "embedded agent_model"
    if llm_identity is None:
        raise IngestError(
            "llm_identity: Retell export names no LLM (the Get Call schema "
            "carries no model field and this export carries no 'agent_model' "
            "ground-truth key) -- pass the backing model explicitly via "
            "from_retell(..., llm_identity=(system, model)), e.g. "
            "('openai', 'gpt-5-mini'); cannot price the call's agent turns "
            "without inventing a model"
        )
    if not isinstance(llm_identity, (tuple, list)) or len(llm_identity) != 2:
        raise IngestError(
            f"llm_identity {llm_identity!r}: expected a (system, model) pair, "
            "e.g. ('openai', 'gpt-5-mini')"
        )
    system, model = llm_identity
    if not isinstance(system, str) or not system.strip():
        raise IngestError(
            f"llm_identity {llm_identity!r}: system must be a non-empty string"
        )
    if not isinstance(model, str) or not model.strip():
        raise IngestError(
            f"llm_identity {llm_identity!r}: model must be a non-empty string "
            "resolving in pricing/rates.yaml"
        )
    # Strip redundant provider prefixes ("openai/gpt-5-mini" -> "gpt-5-mini"):
    # the rate key is f"{system}/{bare_model}" per pricing/rates.yaml convention.
    return system.strip(), model.strip().split("/")[-1].strip(), source


def _asr_identity() -> tuple[str, str]:
    """(system, model) for ASR -- Retell names no transcriber, so the ingest
    defaults (deepgram/nova-3)."""
    return "deepgram", "nova-3"


def _telephony(call_obj: dict[str, Any], telephony_provider: str) -> dict[str, Any] | None:
    """The call's single telephony leg, or None for web calls (which have no
    phone leg -- D8 is then honestly ABSENT via the existing envelope).

    Retell names no PSTN provider, so ``telephony_provider`` (default
    ``"twilio"``) is a caller-supplied assumption, documented loudly; the
    rate key ``<provider>/pstn_<direction>`` must exist in
    ``pricing/rates.yaml`` or loading fails naming the key.
    """
    call_type = call_obj.get("call_type")
    if call_type == "web_call":
        return None
    if call_type != "phone_call":
        raise IngestError(
            f"call_type {call_type!r}: expected 'phone_call' or 'web_call'"
        )
    if not isinstance(telephony_provider, str) or not telephony_provider.strip():
        raise IngestError(
            f"telephony_provider {telephony_provider!r}: expected a "
            "non-empty provider string (Retell names no PSTN provider; the "
            "default 'twilio' is an assumption -- the rate key "
            "'<provider>/pstn_<direction>' must exist in pricing/rates.yaml)"
        )
    direction = call_obj.get("direction")
    if direction not in ("inbound", "outbound"):
        raise IngestError(
            f"direction {direction!r}: phone_call expects 'direction' "
            "'inbound'|'outbound'"
        )
    duration = call_obj.get("duration_ms")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
        raise IngestError(
            f"duration_ms {duration!r}: phone_call expects a non-negative "
            "'duration_ms' for billing"
        )
    return {"provider": telephony_provider.strip(), "direction": direction,
            "billable_seconds": max(1, int(round(duration / 1000)))}


def _token_totals(call_obj: dict[str, Any], *, n_llm_turns: int) -> tuple[list[int], list[int], list[int]]:
    """Per-turn token shares from the call-level ``llm_token_usage`` total.

    Retell emits only a COMBINED per-request count (no prompt/completion
    split), so the combined total is even-split across LLM turns as
    ``input_tokens`` with ``output_tokens`` 0 (exact sum preserved in
    ``input``); output cost is unmeasured, not zero. ``latency`` /
    ``call_cost`` are billing/diagnostic summaries, never token sources.
    """
    usage = call_obj.get("llm_token_usage")
    values = usage.get("values") if isinstance(usage, dict) else None
    if not isinstance(values, list) or not values:
        raise IngestError(
            "llm_token_usage: Retell export carries no LLM token totals "
            "(expected llm_token_usage.values as a non-empty list; absent "
            "when using custom LLM / realtime API / no LLM call is made) -- "
            "per-turn LLM tokens cannot be derived without inventing them"
        )
    total = 0
    for position, value in enumerate(values):
        total += _require_int(value, path=f"llm_token_usage.values[{position}]")
    if total == 0:
        raise IngestError(
            "llm_token_usage.values: token counts sum to 0 while the call "
            f"has {n_llm_turns} agent turn(s) -- per-turn LLM tokens cannot "
            "be derived without inventing them"
        )
    return (
        _split_total(total, n_llm_turns, path="llm_token_usage.values"),
        [0] * n_llm_turns,
        [0] * n_llm_turns,
    )


def _wordless_utterances(entries: list[dict[str, Any]], *, path: str) -> int:
    """Count spoken utterances without usable word timings (fallback note)."""
    count = 0
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            continue
        kind, node = _normalize_entry(raw, index, path=path)
        if kind not in ("user", "transfer", "assistant"):
            continue
        words = node.get("words")
        usable = (
            isinstance(words, list) and bool(words)
            and isinstance(words[0], dict) and isinstance(words[-1], dict)
            and _as_number(words[0].get("start")) is not None
            and _as_number(words[-1].get("end")) is not None
        )
        if not usable:
            count += 1
    return count


def from_retell(call_obj: dict[str, Any], *,
                tool_kinds: dict[str, str] | None = None,
                llm_identity: tuple[str, str] | list[str] | None = None,
                telephony_provider: str = "twilio") -> IngestCall:
    """Map ONE Retell Get Call object to the external ``IngestCall`` format.

    ``tool_kinds`` optionally pins ground truth for tool names
    (``{tool_name: kind}``); without it, :data:`TOOL_KIND_RULES` applies and
    unknown names raise :class:`IngestError`. ``llm_identity`` is the
    ``(system, model)`` pair backing the Retell agent (Retell names
    no model); it falls back to the export's own ``agent_model``
    ``{system, model}`` fixture key when present. When the call has agent
    turns and neither was supplied, adaptation raises :class:`IngestError`
    naming the gap.
    ``telephony_provider`` names the PSTN provider assumed for
    ``phone_call`` legs (Retell names none; default ``"twilio"``, documented
    loudly -- the rate key must exist in ``pricing/rates.yaml``).

    Raises :class:`IngestError` with the source field path on anything
    unmappable -- never a silent drop.
    """
    if not isinstance(call_obj, dict):
        raise IngestError(f"retell call: expected an object, got {type(call_obj).__name__}")
    if "call_id" not in call_obj:
        raise IngestError("call_id: Retell export object has no 'call_id' -- not a call object")

    call_id = str(call_obj["call_id"])
    status = call_obj.get("call_status")
    if status != "ended":
        raise IngestError(
            f"call_status {status!r}: only 'ended' Retell calls are ingestible "
            f"(call {call_id!r} has call_status {status!r} -- re-export after "
            "the call ends)"
        )
    end_reason = map_end_reason(call_obj.get("disconnection_reason"))

    started = _parse_epoch_ms(call_obj.get("start_timestamp"), path="start_timestamp")
    ended = _parse_epoch_ms(call_obj.get("end_timestamp"), path="end_timestamp")
    try:
        call_duration_ms = max(0, int(round((ended - started).total_seconds() * 1000)))
    except (OverflowError, OSError):
        call_duration_ms = 0

    entries, timeline_path = _timeline(call_obj)

    # -- Pass 1: role-normalize (document order; Retell tool entries carry no
    #    timing of their own, so there is no sort key -- the export order IS
    #    the conversation order) ------------------------------------------ #
    ordered: list[tuple[int, dict[str, Any], str]] = []
    for index, raw in enumerate(entries):
        kind, node = _normalize_entry(raw, index, path=timeline_path)
        if kind in ("skip", "info"):
            continue  # dtmf/sms/injected: not spoken; node_transition: informational
        ordered.append((index, node, kind))
    if not ordered:
        raise IngestError(
            f"retell call {call_id!r}: no mappable conversation turns "
            "(timeline holds only dtmf/sms/injected/node_transition entries)"
        )

    # -- Pass 2: group into turns ---------------------------------------- #
    # Each user (or transfer_target) utterance opens a turn; agent/tool
    # entries attach to the open turn. Leading agent/tool entries before the
    # first user utterance (e.g. the greeting) form an opening agent-first
    # turn of their own -- merging them into the first caller turn would join
    # two unrelated agent utterances into one decision. Tool results join
    # their tool call's turn by id afterwards.
    def _new_turn() -> dict[str, Any]:
        return {"asr": None, "agents": [], "toolcalls": [], "results": {}}

    turns: list[dict[str, Any]] = []
    pending: dict[str, Any] = _new_turn()  # leading buffer before the first user msg
    current: dict[str, Any] | None = None
    result_nodes: list[tuple[int, dict[str, Any]]] = []

    for index, node, kind in ordered:
        if kind in ("user", "transfer"):
            if current is not None:
                turns.append(current)
            elif pending["agents"] or pending["toolcalls"] or pending["asr"]:
                turns.append(pending)
                pending = _new_turn()
            current = _new_turn()
            current["asr"] = (index, node)
        elif kind == "assistant":
            (current if current is not None else pending)["agents"].append((index, node))
        elif kind == "invocation":
            call = _invocation_in(node, index, path=timeline_path)
            (current if current is not None else pending)["toolcalls"].append(
                (index, node, call))
        elif kind == "result":
            result_nodes.append((index, node))
    if current is not None:
        turns.append(current)
    elif pending["agents"] or pending["toolcalls"] or pending["asr"]:
        turns.append(pending)
    if not turns or all(not (t["asr"] or t["agents"] or t["toolcalls"]) for t in turns):
        raise IngestError(
            f"retell call {call_id!r}: no mappable conversation turns "
            "(timeline holds no user/agent/tool entries)"
        )

    results_by_id: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, node in result_nodes:
        tool_id = node.get("tool_call_id")
        if isinstance(tool_id, str) and tool_id and tool_id not in results_by_id:
            results_by_id[tool_id] = (index, node)
    for turn in turns:
        turn["results"] = {}

    # -- Pass 3: identities + token shares -------------------------------- #
    n_llm_turns = sum(1 for t in turns if t["agents"])
    llm_system = llm_model = ""
    llm_source = ""
    if n_llm_turns:
        llm_system, llm_model, llm_source = _llm_identity(call_obj, llm_identity)
    asr_system, asr_model = _asr_identity()
    if n_llm_turns:
        prompt_shares, completion_shares, cached_shares = _token_totals(
            call_obj, n_llm_turns=n_llm_turns)
    else:
        prompt_shares = completion_shares = cached_shares = []

    scenario = _scenario(call_obj)
    telephony = _telephony(call_obj, telephony_provider)

    # -- Pass 4: build IngestCall turns ------------------------------------ #
    ingest_turns: list[dict[str, Any]] = []
    llm_seen = 0
    n_entries = len(entries)
    for turn_index, turn in enumerate(turns):
        member_windows: list[tuple[int, int]] = []
        asr_block: dict[str, Any] | None = None
        if turn["asr"] is not None:
            index, node = turn["asr"]
            start_ms, duration_ms, _ = _utterance_window(
                node, call_duration_ms=call_duration_ms, slot=index, n_slots=n_entries)
            member_windows.append((start_ms, start_ms + duration_ms))
            text = node.get("content")
            if not isinstance(text, str) or not text.strip():
                raise IngestError(
                    f"{timeline_path}[{index}]: caller utterance has no text"
                )
            asr_block = {"transcript": text, "start_ms": start_ms,
                         "duration_ms": duration_ms, "model": asr_model,
                         "system": asr_system}

        agent_texts: list[str] = []
        agent_windows: list[tuple[int, int]] = []
        for index, node in turn["agents"]:
            start_ms, duration_ms, _ = _utterance_window(
                node, call_duration_ms=call_duration_ms, slot=index, n_slots=n_entries)
            member_windows.append((start_ms, start_ms + duration_ms))
            agent_windows.append((start_ms, duration_ms))
            text = node.get("content")
            if isinstance(text, str) and text.strip():
                agent_texts.append(text)

        tools: list[dict[str, Any]] = []
        for tc_index, tc_node, call in turn["toolcalls"]:
            kind = infer_tool_kind(call["name"], tool_kinds=tool_kinds,
                                   path=f"{timeline_path}[{tc_index}]")
            res = results_by_id.get(call["id"])
            res_index, res_node = res if res is not None else (None, None)
            if res_node is not None:
                effect, tstatus = resolve_tool_effect(
                    kind, content=res_node.get("content"),
                    successful=res_node.get("successful"),
                    has_result=True, tool_name=call["name"],
                    path=f"{timeline_path}[{res_index}]")
                result_payload = res_node.get("content")
            else:
                effect, tstatus = resolve_tool_effect(
                    kind, content=None, successful=None, has_result=False,
                    tool_name=call["name"],
                    path=f"{timeline_path}[{tc_index}]")
                result_payload = None
            # Retell tool entries carry no timing of their own: start/
            # duration stay None so the adapter falls back to the turn start
            # (no invented timing).
            tools.append({"name": call["name"], "kind": kind, "effect": effect,
                          "args": call["arguments"], "status": tstatus,
                          "result": result_payload})

        llm_block: dict[str, Any] | None = None
        tts_block: dict[str, Any] | None = None
        if turn["agents"]:
            output_text = " ".join(agent_texts)
            if not output_text.strip():
                raise IngestError(
                    f"retell call {call_id!r} turn {turn_index}: agent "
                    "utterances carry no text -- IngestCall requires "
                    "llm.output_text (never copied from tts.text)"
                )
            has_mutating = any(
                t.get("kind") in ("mutation", "handoff") for t in tools)
            decision_kind = _infer_decision_kind(
                turn_index, is_first_llm_turn=(llm_seen == 0),
                has_mutating_tool=has_mutating)
            if decision_kind == "route":
                decision = scenario
                candidates: list[str] | None = [scenario, "other"]
            elif decision_kind == "tool_select":
                decision = tools[0]["name"] if tools else "respond"
                candidates = None
            else:
                decision, candidates = "respond", None
            # Agent-utterance union window for llm/tts timing; llm takes the
            # opening slice so overlapping spans stay inside turn bounds.
            union_start = min(s for s, _ in agent_windows)
            union_end = max(s + d for s, d in agent_windows)
            llm_dur = max(0, (union_end - union_start) // 2 or (union_end - union_start))
            llm_block = {"model": llm_model, "input_tokens": prompt_shares[llm_seen],
                         "output_tokens": completion_shares[llm_seen],
                         "decision_kind": decision_kind, "decision": decision,
                         "output_text": output_text, "start_ms": union_start,
                         "duration_ms": llm_dur, "system": llm_system,
                         "cache_read_tokens": cached_shares[llm_seen]}
            if candidates is not None:
                llm_block["decision_candidates"] = candidates
            # TTS text WITHOUT char counts: the adapter downstream emits no
            # tts/playback spans (G2), and the pipeline reports D6/D7/D8
            # ABSENT. Timing rides the spoken window.
            tts_block = {"text": output_text, "start_ms": union_start,
                         "duration_ms": max(0, union_end - union_start)}
            member_windows.append((union_start, union_end))
            llm_seen += 1

        if not member_windows:
            continue  # a turn left with no timed content carries nothing
        turn_start = min(s for s, _ in member_windows)
        turn_end = max(e for _, e in member_windows)
        if turn_end <= turn_start:
            turn_end = turn_start + 1
        block: dict[str, Any] = {"start_ms": turn_start, "end_ms": turn_end,
                                 "speaker_first": "caller" if turn["asr"] is not None else "agent"}
        if asr_block is not None:
            block["asr"] = asr_block
        if llm_block is not None:
            block["llm"] = llm_block
        if tts_block is not None:
            block["tts"] = tts_block
        if tools:
            block["tools"] = tools
        ingest_turns.append(block)

    if not ingest_turns:
        raise IngestError(
            f"retell call {call_id!r}: no mappable conversation turns after grouping"
        )

    adapted = IngestCall.model_validate({
        "id": call_id, "scenario": scenario,
        "started": started.isoformat(), "ended": ended.isoformat(),
        "end_reason": end_reason, "agent_version": _agent_version(call_obj),
        **({"telephony": telephony} if telephony is not None else {}),
        "turns": ingest_turns,
    })
    return adapted


def from_retell_export(obj: dict[str, Any] | list[Any], *,
                       tool_kinds: dict[str, str] | None = None,
                       llm_identity: tuple[str, str] | list[str] | None = None,
                       telephony_provider: str = "twilio") -> list[IngestCall]:
    """Map a Retell export payload to ``IngestCall``s.

    Accepts a single call object, a bare list of them, or a list-wrapper
    object (``{"calls": [...]}``, ``{"results": [...]}``, or
    ``{"data": [...]}``). Raises :class:`IngestError` on anything else.
    ``llm_identity`` / ``telephony_provider`` pass through to
    :func:`from_retell` for every call in the payload.
    """
    if isinstance(obj, list):
        items = obj
    elif isinstance(obj, dict):
        for wrapper in ("calls", "results", "data"):
            if wrapper in obj:
                wrapped = obj[wrapper]
                if not isinstance(wrapped, list) or not wrapped:
                    raise IngestError(
                        f"retell export: '{wrapper}' must be a non-empty list"
                    )
                items = wrapped
                break
        else:
            if ("call_id" in obj or "disconnection_reason" in obj
                    or "transcript_object" in obj
                    or "transcript_with_tool_calls" in obj):
                items = [obj]
            else:
                raise IngestError(
                    "retell export: expected one call object (with 'call_id'), "
                    "a bare list, or a wrapper with 'calls'/'results'/'data' "
                    "-- see docs/INGEST.md"
                )
    else:
        raise IngestError(
            "retell export: expected one call object, a list, or a "
            "'calls'/'results'/'data' wrapper"
        )
    if not items:
        raise IngestError("retell export: call list is empty")
    return [from_retell(item, tool_kinds=tool_kinds, llm_identity=llm_identity,
                        telephony_provider=telephony_provider) for item in items]


# --------------------------------------------------------------------------- #
# Provenance                                                                   #
# --------------------------------------------------------------------------- #

def inferred_decision_turns(adapted: IngestCall) -> set[int]:
    """Turn indexes whose ``decision_kind`` is inferred, not agent-emitted.

    Retell emits no ``decision_kind`` at all, so this is every turn carrying
    an LLM block. The pipeline uses it for the honesty gate (D1 suppression).
    """
    return {i for i, turn in enumerate(adapted.turns) if turn.llm is not None}


def provenance_note(call_obj: dict[str, Any], adapted: IngestCall) -> str:
    """Human-readable provenance line riding through to the dashboard."""
    n_inferred = len(inferred_decision_turns(adapted))
    n_turns = len(adapted.turns)
    usage = call_obj.get("llm_token_usage")
    values = usage.get("values") if isinstance(usage, dict) else None
    if isinstance(values, list) and values and n_inferred:
        token_clause = (
            f"tokens: call-level llm_token_usage combined total "
            f"{sum(int(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))} "
            f"({len(values)} request counts, no prompt/completion split) "
            "distributed evenly across LLM turns as input_tokens with "
            "output_tokens 0 (exact sum preserved in input; per-turn "
            "attribution approximate; output cost unmeasured, not zero). "
        )
    else:
        token_clause = (
            "tokens: no agent turns carry LLM telemetry (no token split needed). "
        )
    try:
        entries, timeline_path = _timeline(call_obj)
        n_wordless = _wordless_utterances(entries, path=timeline_path)
    except IngestError:
        n_wordless = 0
    if n_wordless:
        timing_clause = (
            f"timing: word start/end are relative-audio-second approximations "
            f"('not guaranteed to be accurate' per Retell docs); {n_wordless} "
            f"utterance(s) carried no word timings and were placed by evenly "
            f"dividing the call duration in document order (approximate, not "
            f"measured). "
        )
    else:
        timing_clause = (
            "timing: word start/end are relative-audio-second approximations "
            "('not guaranteed to be accurate' per Retell docs). "
        )
    if call_obj.get("call_type") == "web_call":
        telephony_clause = "telephony: web_call carries no phone leg (D8 ABSENT). "
    else:
        telephony_clause = (
            "telephony: phone_call leg bills via the caller-supplied provider "
            "(Retell names no PSTN provider; the default 'twilio' is an "
            "assumption -- the '<provider>/pstn_<direction>' rate key must "
            "exist in pricing/rates.yaml). "
        )
    return (
        f"source: {PROVIDER} export (export version {EXPORT_VERSION}, Retell "
        f"Get Call spec rev {SPEC_REVISION}). "
        + _model_clause(call_obj, adapted) +
        f"decision_kind: inferred on {n_inferred}/{n_turns} turn(s) "
        "(route-first / tool_select-on-mutation / compose; never agent-emitted; "
        "D1 excluded from measured waste). "
        + token_clause +
        "tts: text+timing only, no char counts -- D6/D7/D8 ABSENT (no data, "
        "not zero). tools: kind from documented name rules unless overridden "
        "via tool_kinds; effect from successful/content markers "
        "(ambiguous=unknown). "
        + timing_clause
        + telephony_clause
    )


def _model_clause(call_obj: dict[str, Any], adapted: IngestCall) -> str:
    """Where the priced LLM identity came from (never invented by the adapter)."""
    llm_turn = next((t.llm for t in adapted.turns if t.llm is not None), None)
    if llm_turn is None:
        return "llm: no agent turns carry LLM telemetry. "
    return (
        f"llm: {llm_turn.system}/{llm_turn.model} via caller-supplied ground "
        "truth (explicit llm_identity, else the export's embedded agent_model "
        "key; Retell names no model). "
    )


def provider_info(call_obj: dict[str, Any], adapted: IngestCall, *,
                  sample: bool = False) -> dict[str, Any]:
    """Pipeline-ready provenance record for one adapted call.

    ``{"source", "note", "inferred_decision_turns"}`` -- the exact shape
    ``pipeline.run_calls(..., provider=...)`` consumes per call id.
    """
    source = ("Retell export (synthetic schema-conformant example)"
              if sample else "Retell export")
    return {"source": source,
            "note": provenance_note(call_obj, adapted),
            "inferred_decision_turns": sorted(inferred_decision_turns(adapted))}
