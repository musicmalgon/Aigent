"""Train a profile-group-safe TF-IDF baseline from locally supplied JSON files."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.src.remind_ai.data.emotion_dataset import (  # noqa: E402
    DatasetValidationError,
    EmotionSample,
    load_json_samples,
)
from ai.src.remind_ai.data.group_split import (  # noqa: E402
    GroupSplitError,
    dataset_structure_statistics,
    select_group_safe_split,
    split_leakage_statistics,
)
from ai.src.remind_ai.models.tfidf_baseline import (  # noqa: E402
    BaselineConfig,
    BaselineError,
    baseline_configs,
    evaluate_model,
    fit_model,
)


class TrainingFailure(RuntimeError):
    """A caller-safe error that never contains source values or input paths."""


def _class_distribution(samples: Sequence[EmotionSample]) -> dict[str, object]:
    counts = Counter(sample.label for sample in samples)
    total = len(samples)
    return {
        "class_count": len(counts),
        "frequencies": dict(sorted(counts.items())),
        "ratios": {
            label: round(count / total, 6) if total else 0.0
            for label, count in sorted(counts.items())
        },
    }


def _split_summary(
    split_samples: Mapping[str, Sequence[EmotionSample]],
    all_samples: Sequence[EmotionSample],
) -> dict[str, object]:
    return {
        "dataset": dataset_structure_statistics(all_samples),
        "splits": {
            name: {
                "record_count": len(samples),
                "profile_count": len({sample.group_id for sample in samples}),
                "class_counts": _class_distribution(samples)["frequencies"],
                "missing_classes": [],
            }
            for name, samples in split_samples.items()
        },
        "overlap_checks": split_leakage_statistics(dict(split_samples)),
    }


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".tfidf-baseline-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
    except Exception as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except Exception:
                pass
        raise TrainingFailure(
            "a baseline output JSON file could not be written safely"
        ) from exc


def _write_readme(path: Path) -> None:
    content = """# TF-IDF baseline output

This directory contains only aggregate metrics, fitted local artifacts, and
safe configuration. It intentionally excludes source dialogue, talk-id,
profile-id, record-level predictions, hashes, and digests.

`validation_metrics.json` selects a model by internal validation macro-F1.
`test_metrics.json` is the one-time internal test result for that selection.
`official_validation_metrics.json` is a reference-only measurement from the
official files and must not be described as final generalization performance,
because the official split has known profile overlap and raw talk-id reuse.
Raw talk-id overlap is a non-blocking reference statistic; split isolation is
validated with profile-id and the (profile-id, talk-id) conversation key.
"""
    try:
        path.write_text(content, encoding="utf-8")
    except Exception as exc:
        raise TrainingFailure(
            "the baseline README could not be written safely"
        ) from exc


def _write_failure_diagnostics(
    output_dir: Path, diagnostics: Mapping[str, object]
) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            output_dir / "split_failure_diagnostics.json",
            {
                "diagnostic_version": "group-split-diagnostics-v1",
                **diagnostics,
            },
        )
    except Exception:
        # The primary safe exception remains useful even if no output directory is writable.
        return


def _save_artifacts(output_dir: Path, fitted: Any) -> None:
    try:
        joblib = importlib.import_module("joblib")
        joblib.dump(fitted.model, output_dir / "model.joblib")
        joblib.dump(fitted.vectorizer, output_dir / "vectorizer.joblib")
    except Exception as exc:
        raise TrainingFailure(
            "the fitted baseline artifacts could not be saved safely"
        ) from exc


def _official_reference_metrics(
    official_train: Sequence[EmotionSample],
    official_validation: Sequence[EmotionSample],
    config: BaselineConfig,
) -> dict[str, object]:
    try:
        fitted = fit_model(official_train, config)
        return {
            "available": True,
            "scope": "reference_only_not_final_generalization",
            "metrics": evaluate_model(fitted, official_validation),
        }
    except BaselineError:
        return {
            "available": False,
            "scope": "reference_only_not_final_generalization",
            "reason": "the official Training subset could not support this baseline configuration",
        }


def train_baseline(
    *,
    train_json: Path,
    validation_json: Path,
    output_dir: Path,
    random_state: int = 42,
    candidate_count: int = 100,
    min_df: int = 3,
    max_features: int | None = None,
    include_combined: bool = False,
) -> dict[str, object]:
    """Run candidate group split, validation selection, and one internal test."""

    official_train = load_json_samples(train_json, "official_train")
    official_validation = load_json_samples(validation_json, "official_validation")
    samples = [*official_train, *official_validation]
    if not samples:
        raise TrainingFailure("the combined approved dataset is empty")
    if len({sample.label for sample in samples}) < 2:
        raise TrainingFailure("at least two emotion.type classes are required")
    try:
        split = select_group_safe_split(
            samples,
            random_state=random_state,
            candidate_count=candidate_count,
        )
    except GroupSplitError as exc:
        _write_failure_diagnostics(output_dir, exc.diagnostics)
        raise TrainingFailure(str(exc)) from exc
    split_samples = {
        "train": split.samples_for(samples, "train"),
        "validation": split.samples_for(samples, "validation"),
        "test": split.samples_for(samples, "test"),
    }
    summary = _split_summary(split_samples, samples)
    overlap = summary["overlap_checks"]
    assert isinstance(overlap, Mapping)
    if any(
        any(value != 0 for value in category.values())
        for name, category in overlap.items()
        if name in {"profile_id_overlap_count", "conversation_key_overlap_count"}
        and isinstance(category, Mapping)
    ):
        raise TrainingFailure(
            "the selected internal split did not satisfy profile and conversation isolation"
        )

    experiments: dict[str, object] = {}
    fitted_by_name: dict[str, Any] = {}
    for config in baseline_configs(
        min_df=min_df,
        max_features=max_features,
        random_state=random_state,
        include_combined=include_combined,
    ):
        fitted = fit_model(split_samples["train"], config)
        fitted_by_name[config.name] = fitted
        experiments[config.name] = {
            "config": {
                "mode": config.mode,
                "min_df": config.min_df,
                "max_features": config.max_features,
                "random_state": config.random_state,
                "max_iter": config.max_iter,
            },
            "metrics": evaluate_model(fitted, split_samples["validation"]),
        }
    selected_name = max(
        experiments,
        key=lambda name: (
            float(experiments[name]["metrics"]["macro_f1"]),  # type: ignore[index]
            name,
        ),
    )
    selected = fitted_by_name[selected_name]
    selected_config = selected.config
    validation_output = {
        "selection_metric": "macro_f1",
        "selected_model": selected_name,
        "experiments": experiments,
    }
    test_output = {
        "selected_model": selected_name,
        "selection_was_completed_before_internal_test": True,
        "metrics": evaluate_model(selected, split_samples["test"]),
    }
    summary["candidate_seed"] = split.candidate_seed
    summary["balance_score"] = split.balance_score
    summary["missing_classes"] = {
        "validation": list(split.missing_validation_classes),
        "test": list(split.missing_test_classes),
    }
    split_warnings: list[str] = []
    if split.missing_validation_classes:
        split_warnings.append(
            "the internal validation split is missing one or more emotion.type classes"
        )
    if split.missing_test_classes:
        split_warnings.append(
            "the internal test split is missing one or more emotion.type classes"
        )
    summary["warnings"] = split_warnings
    splits_summary = summary["splits"]
    assert isinstance(splits_summary, dict)
    validation_summary = splits_summary["validation"]
    test_summary = splits_summary["test"]
    assert isinstance(validation_summary, dict)
    assert isinstance(test_summary, dict)
    validation_summary["missing_classes"] = list(split.missing_validation_classes)
    test_summary["missing_classes"] = list(split.missing_test_classes)
    summary["official_source_record_counts"] = {
        "train": len(official_train),
        "validation": len(official_validation),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "split_summary.json", summary)
    _write_json(output_dir / "validation_metrics.json", validation_output)
    _write_json(output_dir / "test_metrics.json", test_output)
    _write_json(
        output_dir / "official_validation_metrics.json",
        _official_reference_metrics(
            official_train, official_validation, selected_config
        ),
    )
    _write_json(
        output_dir / "label_classes.json",
        {
            "label_field": "$.profile.emotion.type",
            "classes": sorted({sample.label for sample in samples}),
        },
    )
    _write_json(
        output_dir / "run_config.json",
        {
            "label_field": "$.profile.emotion.type",
            "input_fields": [
                "$.talk.content.HS01",
                "$.talk.content.HS02",
                "$.talk.content.HS03",
            ],
            "turn_separator": " [TURN] ",
            "system_response_fields_included": False,
            "group_field": "$.talk.id.profile-id",
            "sample_id_field": "$.talk.id.talk-id",
            "conversation_key_fields": [
                "$.talk.id.profile-id",
                "$.talk.id.talk-id",
            ],
            "raw_talk_id_overlap_is_blocking": False,
            "random_state": random_state,
            "candidate_count": candidate_count,
            "min_df": min_df,
            "max_features": max_features,
            "official_validation_scope": "reference_only_not_final_generalization",
        },
    )
    _save_artifacts(output_dir, selected)
    _write_readme(output_dir / "README.md")
    return {"selected_model": selected_name, "split_summary": summary}


def _validate_paths(train_json: Path, validation_json: Path, output_dir: Path) -> None:
    if not all(
        path.is_absolute() for path in (train_json, validation_json, output_dir)
    ):
        raise TrainingFailure("all input and output paths must be absolute")
    if not train_json.is_file() or not validation_json.is_file():
        raise TrainingFailure("a required JSON input file is unavailable")
    if (
        train_json.suffix.casefold() != ".json"
        or validation_json.suffix.casefold() != ".json"
    ):
        raise TrainingFailure("both input files must be JSON files")
    if train_json.resolve() == validation_json.resolve():
        raise TrainingFailure("Training and Validation inputs must be separate files")
    if output_dir.resolve() in {train_json.resolve(), validation_json.resolve()}:
        raise TrainingFailure("the output directory must be separate from input files")


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise TrainingFailure("command arguments are invalid")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Train a group-safe TF-IDF baseline without serializing source dialogue or IDs."
    )
    parser.add_argument("--train-json", required=True)
    parser.add_argument("--validation-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--candidate-count", type=_positive_int, default=200)
    parser.add_argument("--min-df", type=_positive_int, default=3)
    parser.add_argument("--max-features", type=_positive_int)
    parser.add_argument("--include-combined", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        arguments = parser.parse_args(argv)
        train_json = Path(arguments.train_json)
        validation_json = Path(arguments.validation_json)
        output_dir = Path(arguments.output_dir)
        _validate_paths(train_json, validation_json, output_dir)
        train_baseline(
            train_json=train_json,
            validation_json=validation_json,
            output_dir=output_dir,
            random_state=arguments.random_state,
            candidate_count=arguments.candidate_count,
            min_df=arguments.min_df,
            max_features=arguments.max_features,
            include_combined=arguments.include_combined,
        )
    except (
        TrainingFailure,
        DatasetValidationError,
        GroupSplitError,
        BaselineError,
    ) as exc:
        print(f"TF-IDF baseline failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print(
            "TF-IDF baseline failed because of an unexpected local processing error",
            file=sys.stderr,
        )
        return 2
    print("TF-IDF baseline completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
