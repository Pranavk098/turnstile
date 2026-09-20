"""Part A tests: label schema, JSONL round-trip, CLI resume, selection rebuild.

Style follows the quality package's existing tests (plain pytest, pydantic
validation checks, tmp_path for file IO).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from turnstile_quality import __main__ as cli
from turnstile_quality.calibration import JUDGE_DIMENSIONS
from turnstile_quality.labeling import (
    LabelRecord,
    append_label_record,
    checked_pairs,
    count_checked,
    find_repo_root,
    is_checked,
    load_selection,
    read_label_records,
    rebuild_selection,
    reference_for,
    render_transcript,
)


def _toy_source(call_id: str, path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "trace": {
                    "conversation": {"conversation_id": call_id},
                    "turns": [
                        {
                            "turn_index": 0,
                            "asr": [{"transcript": f"caller says {call_id}"}],
                            "llm": [{"output_text": f"agent replies {call_id}"}],
                            "tts": [],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )


def _toy_selection(tmp_path: Path, call_ids=("toy-a", "toy-b")) -> Path:
    conversations = []
    for call_id in call_ids:
        source = tmp_path / f"{call_id}.json"
        _toy_source(call_id, source)
        conversations.append({"call_id": call_id, "source": str(source)})
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {"seed": 0, "selection_note": "toy", "conversations": conversations},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return selection


def _seed_reference_rows(labels_path: Path, call_ids=("toy-a", "toy-b")) -> None:
    for call_id in call_ids:
        for dim_id in JUDGE_DIMENSIONS:
            append_label_record(
                labels_path,
                LabelRecord(
                    call_id=call_id,
                    dim_id=dim_id,
                    reference_label="pass",
                    reference_confidence=0.8,
                ),
            )


def test_unknown_dim_id_rejected():
    with pytest.raises(ValidationError):
        LabelRecord(call_id="c1", dim_id="invented_dimension", human_label="pass")


def test_known_dim_ids_accepted():
    for dim_id in JUDGE_DIMENSIONS:
        record = LabelRecord(call_id="c1", dim_id=dim_id, human_label="fail")
        assert record.dim_id == dim_id


@pytest.mark.parametrize("confidence", [-0.01, -1.0, 1.01, 2.0])
def test_confidence_out_of_range_rejected(confidence):
    with pytest.raises(ValidationError):
        LabelRecord(
            call_id="c1",
            dim_id="faithfulness",
            reference_label="pass",
            reference_confidence=confidence,
        )


@pytest.mark.parametrize("confidence", [float("nan"), float("inf")])
def test_confidence_non_finite_rejected(confidence):
    with pytest.raises(ValidationError):
        LabelRecord(
            call_id="c1",
            dim_id="faithfulness",
            reference_label="pass",
            reference_confidence=confidence,
        )


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0, None])
def test_confidence_boundaries_accepted(confidence):
    record = LabelRecord(
        call_id="c1",
        dim_id="faithfulness",
        reference_label="pass",
        reference_confidence=confidence,
    )
    assert record.reference_confidence == confidence


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        LabelRecord(call_id="c1", dim_id="faithfulness", bogus_field="x")  # type: ignore[call-arg]


def test_unchecked_rows_never_count_toward_n():
    rows = [
        LabelRecord(
            call_id="c1",
            dim_id="faithfulness",
            reference_label="pass",
            reference_confidence=0.9,
        ),
        LabelRecord(call_id="c1", dim_id="faithfulness", human_label="pass",
                    rater="ann"),
        LabelRecord(call_id="c2", dim_id="answer_relevance", human_label="fail",
                    rater="ann"),
    ]
    assert is_checked(rows[0]) is False
    assert checked_pairs(rows) == {("c1", "faithfulness"), ("c2", "answer_relevance")}
    assert count_checked(rows) == {"faithfulness": 1, "answer_relevance": 1}


def test_jsonl_round_trip(tmp_path):
    labels = tmp_path / "labels.jsonl"
    rows = [
        LabelRecord(call_id="c1", dim_id="faithfulness", human_label="pass",
                    rater="ann", note="clear"),
        LabelRecord(
            call_id="c1",
            dim_id="answer_relevance",
            reference_label="fail",
            reference_confidence=0.62,
        ),
    ]
    for row in rows:
        append_label_record(labels, row)
    assert read_label_records(labels) == rows


def test_read_missing_labels_file_is_empty(tmp_path):
    assert read_label_records(tmp_path / "nope.jsonl") == []


def test_reference_for_returns_latest_pre_label(tmp_path):
    labels = tmp_path / "labels.jsonl"
    append_label_record(
        labels,
        LabelRecord(call_id="c1", dim_id="faithfulness",
                    reference_label="fail", reference_confidence=0.55),
    )
    append_label_record(
        labels,
        LabelRecord(call_id="c1", dim_id="faithfulness",
                    reference_label="pass", reference_confidence=0.91),
    )
    records = read_label_records(labels)
    assert reference_for(records, "c1", "faithfulness").reference_label == "pass"
    assert reference_for(records, "c1", "answer_relevance") is None


def test_render_transcript_shows_caller_and_agent():
    lines = render_transcript(
        {
            "trace": {
                "turns": [
                    {
                        "turn_index": 0,
                        "asr": [{"transcript": "hi"}],
                        "llm": [{"output_text": "hello"}],
                        "tts": [],
                    },
                    {"turn_index": 1, "asr": [], "llm": [], "tts": []},
                ]
            }
        }
    )
    assert lines[0] == "T0 caller: hi"
    assert lines[1] == "T0 agent: hello"
    assert "(no text" in lines[2]


def test_render_transcript_handles_golden_dotted_keys():
    lines = render_transcript(
        {
            "conversation": {"conversation_id": "g"},
            "turns": [
                {
                    "turn_index": 0,
                    "asr": [],
                    "llm": [{"turnstile.output_text": "Let me check that."}],
                    "tts": [],
                }
            ],
        }
    )
    assert lines == ["T0 agent: Let me check that."]


def test_label_cli_resume_after_checked_row(tmp_path, monkeypatch, capsys):
    """Pre-checked (toy-a, faithfulness) is skipped; scripted y/n/q drive
    the next pairs; rows carry rater + checked_at; history untouched."""
    selection = _toy_selection(tmp_path)
    labels = tmp_path / "labels.jsonl"
    _seed_reference_rows(labels)
    append_label_record(
        labels,
        LabelRecord(
            call_id="toy-a",
            dim_id="faithfulness",
            reference_label="pass",
            reference_confidence=0.8,
            human_label="pass",
            rater="ann",
            checked_at="2026-09-17T00:00:00+00:00",
        ),
    )
    before = labels.read_text(encoding="utf-8")

    answers = iter(["y", "n", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    code = cli.main(
        ["label", "--selection", str(selection),
         "--labels", str(labels), "--rater", "ann"]
    )
    assert code == 0
    out = capsys.readouterr().out

    # Transcript display + reference pre-label shown for the resumed pair.
    assert "caller says toy-a" in out
    assert "reference pre-label: pass" in out

    rows = read_label_records(labels)
    assert labels.read_text(encoding="utf-8").startswith(before)  # append-only
    assert len(rows) == 7  # 4 reference + 1 pre-checked + 2 new verdicts

    appended = rows[-2:]
    # 'y' agrees with reference pass; 'n' flips reference pass -> fail.
    assert appended[0].call_id == "toy-a"
    assert appended[0].dim_id == "answer_relevance"
    assert appended[0].human_label == "pass"
    assert appended[1].call_id == "toy-b"
    assert appended[1].dim_id == "faithfulness"
    assert appended[1].human_label == "fail"
    for row in appended:
        assert row.rater == "ann"
        assert row.checked_at is not None
        assert row.reference_label == "pass"  # pre-label carried into the row


def test_label_cli_quit_first_leaves_history_untouched(
    tmp_path, monkeypatch, capsys
):
    selection = _toy_selection(tmp_path, call_ids=("toy-a",))
    labels = tmp_path / "labels.jsonl"
    _seed_reference_rows(labels, call_ids=("toy-a",))
    before = labels.read_text(encoding="utf-8")

    monkeypatch.setattr("builtins.input", lambda _prompt="": "q")
    assert (
        cli.main(
            ["label", "--selection", str(selection),
             "--labels", str(labels), "--rater", "ann"]
        )
        == 0
    )
    assert labels.read_text(encoding="utf-8") == before
    assert "re-run to resume" in capsys.readouterr().out


def test_stats_subcommand_reports_labeled_per_total(
    tmp_path, monkeypatch, capsys
):
    selection = _toy_selection(tmp_path)
    labels = tmp_path / "labels.jsonl"
    _seed_reference_rows(labels)  # unchecked: must not count
    append_label_record(
        labels,
        LabelRecord(call_id="toy-a", dim_id="faithfulness",
                    human_label="pass", rater="ann"),
    )
    assert (
        cli.main(
            ["stats", "--selection", str(selection), "--labels", str(labels)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "faithfulness: 1/2 labeled" in out
    assert "answer_relevance: 0/2 labeled" in out


def test_selection_rebuild_is_byte_identical():
    """The committed manifest re-derives to identical bytes from data."""
    root = find_repo_root(Path(__file__))
    committed = root / "fixtures" / "calibration" / "selection.json"
    before = committed.read_bytes()
    assert len(json.loads(before)["conversations"]) >= 60
    rebuild_selection(committed, root)
    assert committed.read_bytes() == before


def test_committed_selection_loads_and_covers_both_sources():
    root = find_repo_root(Path(__file__))
    selection = load_selection(
        root / "fixtures" / "calibration" / "selection.json", root
    )
    sources = [entry["source"] for entry in selection["conversations"]]
    assert any(source.startswith("fixtures/golden/") for source in sources)
    assert any(source.startswith("packages/ingest/data/") for source in sources)
    assert selection["seed"] == 4
    assert "golden" in selection["selection_note"]
