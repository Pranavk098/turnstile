"""Jev decision/audit harness — Turnstile's constrained way to use TypeSafe AI.

We (human + System-Two LLM) invent options. Jev (System-One) only votes:
  state = {decision, options, assumptions, evidence, code_ref}
  questions = 1x Choice (best option) + Nx Noul (assumption holds?) + 1x Score (risk)

No open-ended questions. No codegen. Confidence gates the result:
  act (>0.85) / review (>0.6) / escalate (else).

Usage:
  python scripts/jev_decide.py --dry-run   # no key, prints payload
  set TYPESAFE_API_KEY=sk-... ; python scripts/jev_decide.py --decision verdict_false_resolve
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

API_URL = "https://api.typesafe.ai/v1/systemone"


def _load_dotenv() -> None:
    # minimal .env loader (KEY=val, no dep): repo-root .env only, env wins.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(root, ".env")
    if not os.path.exists(p):
        return
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


_load_dotenv()
MODEL = os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest")

# ponytail: curated decision records, add new ones here instead of new files.
DECISIONS = {
    "verdict_false_resolve": {
        "decision": "Is verdict adjudicate.py FALSE_RESOLVE binding (B3) correct?",
        "options": {
            "keep": "Keep B3: completion keyword + intent token from scenario_id/tool_name",
            "tighten": "Tighten: require scenario registry match only",
            "loosen": "Loosen: keyword alone triggers FALSE_RESOLVE",
        },
        "assumptions": [
            "B3 never fires FALSE_RESOLVE when no intent tokens are derivable",
            "Terminal effect=unknown caps confidence at 0.6 and forbids RESOLVED",
        ],
        "evidence": {
            "code_ref": "packages/verdict/src/turnstile_verdict/adjudicate.py:22-28",
            "tests": "packages/verdict tests green; 23 golden fixtures",
            "method_bound": "docs/METHOD.md: verdict labels ride on terminal tool effect (H-1)",
        },
    },
    "schema_pricing": {
        "decision": "Is per-turn pricing (TTS base, telephony split, ToolCall validation) the right implementation?",
        "options": {
            "synth": "TTS cost on synthesized chars (current pricing.py:73-75)",
            "played": "TTS cost on played chars only",
            "max": "TTS cost on max(synth, played)",
        },
        "assumptions": [
            "Telephony $X on zero-wall traces must split evenly per turn so sum(stages)==conv_cost",
            "ToolCall(mutation, status=error, effect=committed) must be rejected by schema validation",
        ],
        "evidence": {
            "code_ref": "pricing.py:60-79,133-165; spans.py:62-73",
            "tests": "test_pricing.py:220-228 synth184!=played61; :247-266 zero-wall split; test_spans.py:122-126 error+committed rejected",
            "method_bound": "TTS billed on synthesized; telephony pro-rata wall; H-1 verdict rides terminal effect",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "Given trace T07 (tts chars_synth=184, played=61, barge_in) + rate piper=0.025/1k: is this the right TTS cost implementation?",
                "criteria": {
                    "synth": "TTS cost on synthesized chars (current)",
                    "played": "TTS cost on played chars only",
                    "max": "TTS cost on max(synth, played)",
                    "other": None,
                },
            },
        },
    },
    "verdict_audit": {
        "decision": "Is verdict evidence precedence + unknown-cap + fork-oracle the right implementation?",
        "options": {
            "keep": "Keep: precedence, unknown cap 0.6, B3 binding, oracle assumptions",
            "fix_binding": "Fix substring/intent-token binding only",
            "fix_oracle": "Fix fork-oracle escalation assumptions only",
        },
        "assumptions": [
            "Terminal mutation effect=unknown with bindable completion claim must stay UNRESOLVED at <=0.60",
            "escalate->continue fork returns None; continue->escalate returns True only under ASSUME_ESCALATION_COMMITS",
        ],
        "evidence": {
            "code_ref": "adjudicate.py:7-19,212-226,265-287; fork_oracle.py:44-45,111-114",
            "tests": "test_adjudicate.py:204-212 unbound->UNRESOLVED; :257-264 unknown cap; test_fork_oracle.py:120-155",
            "method_bound": "METHOD.md:146-151 clean-close leniency; :128-131 open-loop required, commit assumption UNVERIFIED",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "scenario refund, terminal tool effect=rejected, final='The report is processed.' (keyword hit, zero intent tokens): is UNRESOLVED@0.80 no-claim the right implementation?",
                "criteria": {
                    "false_resolve": "FALSE_RESOLVE@0.90",
                    "unresolved": "UNRESOLVED@0.80 no-claim (current)",
                    "partially": "PARTIALLY_RESOLVED@0.75",
                    "other": None,
                },
            },
        },
    },
    "detectors_audit": {
        "decision": "Are detector thresholds and attribution rules (D3/D8/D9) the right implementation?",
        "options": {
            "keep": "Keep verbatim thresholds + current attribution",
            "tune": "Tune thresholds + attribution on real traffic before claiming",
            "gate": "Gate shaky detectors to ABSENT until calibrated",
        },
        "assumptions": [
            "A 250ms post-TTS trailing silence on real audio bills to asr_endpoint via the trailing-gap table",
            "D9-T1 charging turns t..end at conf 0.5 is a fair stand-in until the live escalation classifier exists",
        ],
        "evidence": {
            "code_ref": "d03:61 COSINE 0.85; d08:43 200ms, :51-57 trailing, :111-124 union; d09:50-51,68-93",
            "tests": "test_d03_cosine stubbed; test_d08 union-not-sum + golden 08 5200ms; D2/D6 never fire on 250-corpus",
            "method_bound": "G1 union==sum live over-reports; D8 Tier-2 modeled; LIMITATIONS.md:62-64 coverage gap",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "D3 live flood: same doc re-fetched, paraphrased query, doc-id miss, cosine 0.82 vs threshold 0.85: is this the right implementation?",
                "criteria": {
                    "structural_only": "Fire on structural overlap only",
                    "lower": "Lower cosine threshold to 0.80",
                    "keep_or": "Keep OR-max(doc-id, cosine) at 0.85 (current)",
                    "other": None,
                },
            },
        },
    },
    "replay_audit": {
        "decision": "Is pinned replay + CR-B arbitrage + kind-aware gate + 8.3 gate the right implementation?",
        "options": {
            "keep": "Keep CR-B-original, label gate, 8.3 gate as-is",
            "real_usage": "Gate margin on real-usage arbitrage instead",
            "open_loop": "Adjudicate divergent forks open-loop instead of excluding",
        },
        "assumptions": [
            "preservation>=0.95 plus bootstrap CI upper bound on delta-cost<0 is the right gate for claiming the 0.57% margin",
            "Unparseable prose forks must count divergent (never silently preserved)",
        ],
        "evidence": {
            "code_ref": "replay.py:110-123,281-287,329-333; margin.py:32-37; stats.py:93-95",
            "tests": "test_repricing arbitrage exactness; test_kind_gate paraphrase-ok/label-fork; test_margin gate+math",
            "method_bound": "METHOD.md:16-23 proven Tier-1; 0.57%[0.49,0.66] n=250 seed0; H-1 structural preservation; seed8 coincidence",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "For route-only savings with pinned tools: is CR-B rate arbitrage on ORIGINAL tokens the right implementation?",
                "criteria": {
                    "crb_original": "Keep CR-B on original tokens (current)",
                    "real_usage": "Gate on real-usage arbitrage",
                    "rebuilt_delta": "Gate on rebuilt-trace delta",
                    "other": None,
                },
            },
        },
    },
    "ingest_audit": {
        "decision": "Are ingest inference rules (TTS omit, kind inference, even-split) the right implementation?",
        "options": {
            "keep": "Keep ABSENT-omit, kind inference, even-split",
            "apportion": "Apportion call-level counts per turn instead of omitting",
            "block": "Block ingest without per-turn evidence instead of inferring",
        },
        "assumptions": [
            "D1 must stay ABSENT and margin-excluded on fully-inferred provider calls",
            "Even-split token attribution is fair for provider calls missing per-turn totals",
        ],
        "evidence": {
            "code_ref": "adapter.py:160-194 omit; vapi.py:457-477 inference; vapi.py:322-333 even-split; pipeline.py:96-97",
            "tests": "test_vapi.py:340-354 omit+inference pins; test_retell.py:564-605 same; D1 fires raw then suppressed",
            "method_bound": "INGEST.md:82-111,210-225; G2 forbids len(text) stand-in; provider traffic yields no measured D1/margin",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "Vapi/Retell export with text+timing but no chars_synthesized/played, telephony present: is omit-spans + ABSENT D6/D7/D8 the right implementation?",
                "criteria": {
                    "absent": "Keep omit + ABSENT (current)",
                    "apportion": "Apportion call-level ttsCharacters per turn",
                    "standin": "len(text) stand-in with discount",
                    "other": None,
                },
            },
        },
    },
    "bargein_audit": {
        "decision": "Is the barge-in harness (chunking atom, 40x/2s assumptions, fake parity) the right implementation?",
        "options": {
            "sentence": "Keep sentence chunking (~4.1% waste, fewest calls)",
            "clause": "Ship clause chunking (~2.3%)",
            "word": "Ship word chunking (~1.2%, most calls/latency)",
        },
        "assumptions": [
            "The 4%-to-1.2% remedy curve measured on local Piper transfers to hosted sub-second streaming pipelines",
            "played=round(synth*fraction) fairly attributes played chars on cut turns",
        ],
        "evidence": {
            "code_ref": "tts.py:33-45,73-91,157-166; sim.py:48,164-199,227-234; bargein.py:81-88",
            "tests": "test_granularity monotone at 0.3s cap; test_piper_engine rate>1 weak; bargein_report.json 4.14%->2.29%",
            "method_bound": "METHOD.md:184-216 harness 4% + live sweep 12.1/31.7/41.4%; fake 10x vs real ~40x",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "Readback call, 15% interrupt rate, 2s lead cap: is sentence-chunked synthesis the right cancellation atom?",
                "criteria": {
                    "sentence": "Keep sentence (~4.1% waste, fewest calls)",
                    "clause": "Ship clause (~2.3%)",
                    "word": "Ship word (~1.2%, most calls/latency)",
                    "other": None,
                },
            },
        },
    },
    "service_audit": {
        "decision": "Are service paid-gating, landing numbers, and honesty labels the right implementation?",
        "options": {
            "keep": "Keep worker-time refuse, hardcoded landing, current label vocab",
            "submit_gate": "Fail closed at submit + generate landing numbers + unify vocab",
            "allow_paid": "Allow paid sweep with confirm + audit trail",
        },
        "assumptions": [
            "Hardcoding 1.32%/4.1%/$0.00135 on the landing page is acceptable while the report fetches live",
            "Proven/Measured/Conditional on UI matches Measured/Instrumented/Not-yet-measured in docs",
        ],
        "evidence": {
            "code_ref": "jobs.py:263-267 refuse; home.html:111-125 hardcoded; index.html:449 label defs",
            "tests": "test_jobs.py:217-228 paid->error; test_home fleet+conditional; test_evaluate labels survive wire",
            "method_bound": "DECISIONS.md:56-65 per-dataset stamped margin; DEPLOY.md $0 claim; cold 22.4s RED vs 5s budget",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "If TURNSTILE_ALLOW_PAID=1 leaks onto Render: is refuse-non-MockBackend at worker-run-time (202 accepted, then error) the right implementation?",
                "criteria": {
                    "worker_refuse": "Keep worker-time refuse (current)",
                    "submit_gate": "Fail closed at submit (422/500, never 202)",
                    "allow_paid": "Allow paid sweep with explicit confirm + audit",
                    "other": None,
                },
            },
        },
    },
    "quality_audit": {
        "decision": "Is quality calibration gating + pending-hold + overall rollup the right implementation?",
        "options": {
            "keep": "Keep closed gate, pending-hold, rollup of scorable dims only",
            "provisional": "Open provisionally with reference-only proxy + instrumented badge",
            "downgrade": "Keep gate but downgrade overall when any dim is pending",
        },
        "assumptions": [
            "120 reference rows with 0 human checks must keep judge dims at pending (never scored)",
            "Overall may report pass on 5/7 dims while 2 judge dims stay pending",
        ],
        "evidence": {
            "code_ref": "calibration.py:25-28,71-86 gate; dimensions.py:348-364,375-413 pending+rollup",
            "tests": "test_calibration gate closed/open/coax; test_agreement pending-never-scores; calibration_report.json n=0",
            "method_bound": "METHOD.md:232-252 quality honesty; LIMITATIONS.md:69-77 pending; McHugh-2012 kappa vector",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "120 reference rows, 0 human checks: is holding judge dims at pending behind n>=60 + kappa>=0.75 the right implementation?",
                "criteria": {
                    "keep_closed": "Keep closed until bar met (current)",
                    "provisional": "Open provisionally with reference-only proxy + instrumented badge",
                    "hide": "Score internally but hide from summary",
                    "other": None,
                },
            },
        },
    },
    "c2_thresholds": {
        "decision": "Keep PRD-verbatim detector thresholds or tune on real-call ROC?",
        "options": {
            "verbatim": "Keep 32-tok / slope400+cache0.5 / cosine0.85 / 200ms (current)",
            "tuned": "Tune per-detector thresholds with CIs + calibration report",
        },
        "assumptions": [
            "Thresholds tuned on synthetic fixtures transfer to live gpt-5-mini traffic",
            "D2/D6 silence on the 250-corpus is a coverage gap, not proof of absence",
        ],
        "evidence": {
            "code_ref": "d01:33; d02:26-27; d03:61; d08:43",
            "tests": "test_fixture_sweep golden-only; D2/D6 never fire on 250-corpus; no live-tuning test",
            "method_bound": "LIMITATIONS.md:62-64 coverage gap; cycle-1 Jev: other 0.50, risk 1.43",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "Live gpt-5-mini traffic: is verbatim or corpus-tuned threshold the right implementation?",
                "criteria": {
                    "verbatim": "Keep PRD-verbatim thresholds (current)",
                    "tuned": "Tune per-detector thresholds with CIs + calibration report",
                    "other": None,
                },
            },
        },
    },
    "c2_ingest_partial": {
        "decision": "Call-level ABSENT or turn-level partial coverage for incomplete acoustic logs?",
        "options": {
            "call_absent": "Keep call-level ABSENT (current)",
            "turn_partial": "Score measurable turns, ABSENT only the incomplete ones",
        },
        "assumptions": [
            "Turn-level partial coverage preserves the honesty labels",
            "One bad turn must not poison a whole call",
        ],
        "evidence": {
            "code_ref": "pipeline.py:71-108,138-140; adapter.py:160-194",
            "tests": "native + provider samples all ABSENT today; D6 would fire every compose turn if passed",
            "method_bound": "INGEST.md:82-111; G2 forbids len(text) stand-in",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "Log with 8/10 TTS turns acoustic-complete: is call-absent or turn-partial the right implementation?",
                "criteria": {
                    "call_absent": "Whole call ABSENT (current)",
                    "turn_partial": "Score 8 turns, ABSENT 2",
                    "other": None,
                },
            },
        },
    },
    "c2_chunk_gate": {
        "decision": "Gate the chunking remedy on CR-B original-token delta or real-usage delta?",
        "options": {
            "crb": "Keep CR-B on original tokens (current)",
            "real_usage": "Gate on real-usage arbitrage companion",
        },
        "assumptions": [
            "Original-token workload approximates the counterfactual chunked workload",
            "Real prompts render ~4x smaller than synthetic, shrinking real savings",
        ],
        "evidence": {
            "code_ref": "replay.py:326-334; margin.py:32-37",
            "tests": "test_repricing exactness; bargein_report.json sweep 4.14%->2.29%",
            "method_bound": "CR-B note: synthetic token scales exceed real render; cycle-1 real_usage mass 0.39",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "Chunking remedy savings claim: is CR-B or real-usage delta the right gate?",
                "criteria": {
                    "crb": "CR-B on original tokens (current)",
                    "real_usage": "Real-usage arbitrage companion",
                    "other": None,
                },
            },
        },
    },
    "c2_ship_default": {
        "decision": "Ship sentence, clause, or word as the default TTS chunking?",
        "options": {
            "sentence": "Sentence default, max synthesis speed (current)",
            "clause": "Clause default, balanced 2.3% waste",
            "word": "Word default, min waste 1.2%",
        },
        "assumptions": [
            "Synthesis-speed cost (41x->27x) is acceptable at clause granularity",
            "Chunking leaves playback UX untouched",
        ],
        "evidence": {
            "code_ref": "variants.py:67-76 harness re-synthesis; tts.py:33-45 atom",
            "tests": "bargein_report.json 4.1%->2.3%->1.2%, gen 41x->27x; cycle-1 Jev leaned clause 0.59",
            "method_bound": "DEMO:21-25 remedy + buffer floor; hosted transfer UNVERIFIED",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "Waste falls sentence->clause->word but gen-rate falls 41x->27x: which default ships?",
                "criteria": {
                    "sentence": "Sentence, max speed (current)",
                    "clause": "Clause, balanced 2.3%",
                    "word": "Word, min waste 1.2%",
                    "other": None,
                },
            },
        },
    },
    "c2_readme_stamp": {
        "decision": "Must the README headline carry the inline (n, dataset) stamp?",
        "options": {
            "fix": "Fix README to stamp 0.57% with (n=250, seed 0) inline",
            "footnote": "Footnote suffices, headline stays bare",
        },
        "assumptions": ["A bare headline number will be misquoted without its dataset"],
        "evidence": {
            "code_ref": "README.md headline; DECISIONS.md:61-62 stamp rule",
            "tests": "No test guards headline text (UNVERIFIED)",
            "method_bound": "Per-dataset margin rule; honesty labels on every surface",
        },
        "questions": {
            "answer": {
                "type": "noul",
                "instructions": "Given the evidence: the README headline must carry the inline (n=250, seed 0) stamp; a footnote alone is insufficient",
            },
        },
    },
    "c2_d8_absent": {
        "decision": "Force live D8 findings ABSENT until the recorder emits overlap?",
        "options": {
            "force_absent": "Force ABSENT until concurrency redesign",
            "tier2_tag": "Show with Tier-2 modeled tag",
        },
        "assumptions": ["Union==sum on non-overlap recorders systematically over-reports silence"],
        "evidence": {
            "code_ref": "d08:26-31,102-130; GATES:17-27",
            "tests": "D8 ~82% corpus share; modeled-gap artifact per LIMITATIONS:64-65",
            "method_bound": "GATES.md: demo-not-measurement until redesign; Tier-2 honesty",
        },
        "questions": {
            "answer": {
                "type": "noul",
                "instructions": "Given the evidence: live D8 findings must be forced ABSENT until the recorder emits overlap",
            },
        },
    },
    "c2_ship_judges": {
        "decision": "With 60 labels at kappa=0.8: report-only calibration or ship paid-gated judges?",
        "options": {
            "report_only": "Report kappa/ECE, keep judges pending",
            "ship_gated": "Ship faithfulness/relevance + verdict source-5 behind paid gate",
        },
        "assumptions": [
            "kappa=0.8 on 60 labels justifies opening judge dimensions",
            "Paid-gating judges preserves the $0 default",
        ],
        "evidence": {
            "code_ref": "calibration.py:71-86 gate; dimensions.py:348-364",
            "tests": "test_calibration opens only at bar; cycle-1 Jev backed closed gate 0.87",
            "method_bound": "LIMITATIONS.md:69-77 pending; PRD kappa mandatory",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "60 labels, kappa=0.8: is report-only or ship-paid-gated the right implementation?",
                "criteria": {
                    "report_only": "Report only, judges stay pending",
                    "ship_gated": "Ship judges behind paid gate",
                    "other": None,
                },
            },
        },
    },
    "c2_hygiene": {
        "decision": "Minimal gate+regen or full e2e+CI guards for the service hardening bundle?",
        "options": {
            "minimal": "Submit gate + regen samples + vocab map (current plan)",
            "full": "Add e2e transfer test + README-count CI guard + link-health job",
        },
        "assumptions": ["Headline drift on regen is a matter of time without guards"],
        "evidence": {
            "code_ref": "app.py:evaluate; dashboard/sample/*; jobs.py",
            "tests": "test_ratelimit caps; no regen-stability or headline guard (UNVERIFIED)",
            "method_bound": "DEPLOY.md $0; cycle-1 Jev wanted submit_gate 0.71",
        },
        "questions": {
            "best_option": {
                "type": "choice",
                "instructions": "Pasted-call eval hitting the paid path: is minimal or full-guards the right implementation?",
                "criteria": {
                    "minimal": "Minimal gate + regen (current plan)",
                    "full": "Full e2e + CI guards",
                    "other": None,
                },
            },
        },
    },
}


def _template_questions(d: dict) -> dict:
    questions = {
        "best_option": {
            "type": "choice",
            "instructions": f"Given the evidence, which option is best? {d['decision']}",
            "criteria": {k: v for k, v in d["options"].items()} | {"other": None},
        },
        "risk": {
            "type": "score",
            "instructions": "Risk of keeping current implementation as-is?",
            "criteria": ["safe to keep", "needs review", "must fix now"],
        },
    }
    for i, a in enumerate(d["assumptions"]):
        questions[f"assumption_{i}"] = {"type": "noul", "instructions": f"Given the evidence: {a}"}
    return questions


def build_payload(key: str) -> dict:
    d = DECISIONS[key]
    questions = d.get("questions") or _template_questions(d)
    if "risk" not in questions:
        questions = {
            **questions,
            "risk": {
                "type": "score",
                "instructions": "Risk of keeping current implementation as-is?",
                "criteria": ["safe to keep", "needs review", "must fix now"],
            },
        }
        for i, a in enumerate(d["assumptions"]):
            questions.setdefault(f"assumption_{i}", {"type": "noul", "instructions": f"Given the evidence: {a}"})
    return {
        "model": MODEL,
        "state": {
            "decision": d["decision"],
            "options": d["options"],
            "assumptions": d["assumptions"],
            "evidence": d["evidence"],
        },
        "questions": questions,
    }


def gate(choice: dict) -> str:
    c = choice.get("confidence", 0)
    return "act" if c > 0.85 else "review" if c > 0.6 else "escalate"


def call_api(payload: dict) -> dict:
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        raise SystemExit("Set TYPESAFE_API_KEY first (console.typesafe.ai/settings/keys).")
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
        return json.load(r)


def demo() -> None:
    for key in DECISIONS:
        p = build_payload(key)
        assert p["questions"], key
        for qk, q in p["questions"].items():
            assert q["type"] in ("choice", "noul", "score"), (key, qk)
    assert gate({"confidence": 0.9}) == "act"
    assert gate({"confidence": 0.7}) == "review"
    assert gate({"confidence": 0.4}) == "escalate"
    print(f"demo ok ({len(DECISIONS)} decisions)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision", default="verdict_false_resolve", choices=list(DECISIONS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-check", action="store_true")
    a = ap.parse_args()
    if a.self_check:
        return demo()
    payload = build_payload(a.decision)
    if a.dry_run:
        return print(json.dumps(payload, indent=2))
    resp = call_api(payload)
    ans = resp.get("answers", {})
    out: dict = {"model": resp.get("model"), "answers": {}}
    for k, v in ans.items():
        t = v.get("type")
        if t == "choice":
            out["answers"][k] = {
                "choice": v.get("choice"),
                "confidence": v.get("confidence"),
                "gate": gate(v),
                "probabilities": v.get("probabilities"),
            }
        elif t == "noul":
            out["answers"][k] = {"noul": v.get("noul")}
        elif t == "score":
            out["answers"][k] = {"score": v.get("score"), "confidence": v.get("confidence")}
    out["usage"] = resp.get("usage")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    sys.exit(main())
