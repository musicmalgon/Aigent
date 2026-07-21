from __future__ import annotations

import csv
from pathlib import Path


AI_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = AI_ROOT / "docs"
EVALUATION_PATH = AI_ROOT / "data" / "evaluation" / "remind_diary_eval.csv"
LABEL_MAP_PATH = DOCS_ROOT / "emotion_label_map.csv"

REMIND_LABELS = {"stable", "fatigue", "anxiety", "other"}
EVALUATION_COLUMNS = {
    "id",
    "text",
    "primary_emotion",
    "secondary_signals",
    "cause_tags",
    "review_status",
    "review_note",
}
REQUIRED_DOCUMENTS = {
    "emotion_label_spec.md",
    "assessment_policy.md",
    "behavioral_baseline_spec.md",
    "scenario_definitions.md",
    "backend_handoff_draft.md",
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        return list(reader.fieldnames or []), list(reader)


def test_required_documents_exist_and_are_not_empty() -> None:
    for filename in REQUIRED_DOCUMENTS:
        document = DOCS_ROOT / filename
        assert document.is_file(), f"Missing required document: {filename}"
        assert document.read_text(encoding="utf-8").strip()


def test_emotion_label_map_is_a_reviewable_draft() -> None:
    fieldnames, rows = read_csv(LABEL_MAP_PATH)

    assert fieldnames == [
        "original_label",
        "remind_label",
        "reason",
        "review_status",
        "notes",
    ]
    assert rows
    assert {row["remind_label"] for row in rows} == REMIND_LABELS
    assert all(row["review_status"] == "draft" for row in rows)
    assert all(row["original_label"].strip() for row in rows)
    assert any("확인" in row["notes"] or "검토" in row["notes"] for row in rows)


def test_diary_evaluation_draft_is_balanced_and_review_gated() -> None:
    fieldnames, rows = read_csv(EVALUATION_PATH)

    assert set(fieldnames) == EVALUATION_COLUMNS
    assert len(rows) == 30
    assert len({row["id"] for row in rows}) == 30
    assert all(row["review_status"] == "needs_human_review" for row in rows)
    assert all(row["text"].strip() for row in rows)
    assert all(
        "합성" in row["review_note"].lower()
        or "synthetic" in row["review_note"].lower()
        for row in rows
    )

    label_counts = {
        label: sum(row["primary_emotion"] == label for row in rows)
        for label in REMIND_LABELS
    }
    assert all(count > 0 for count in label_counts.values())
    assert max(label_counts.values()) - min(label_counts.values()) <= 2
