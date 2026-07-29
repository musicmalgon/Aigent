"""Train a profile-group-safe TF-IDF baseline from locally supplied JSON files."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.src.remind_ai.data.emotion_dataset import (
    DatasetValidationError,
    EmotionSample,
    load_json_samples,
)
from ai.src.remind_ai.data.emotion_label_mapping import (
    EmotionLabelMappingError,
    load_emotion_label_mapping,
)
from ai.src.remind_ai.data.emotion_taxonomy_v2 import (
    REMIND_COARSE_V2,
    EmotionTaxonomyV2Error,
    load_annotation_manifest,
    load_emotion_label_policy_v2,
    prepare_remind_coarse_v2,
    safe_policy_payload,
    validate_dataset_release_id,
)
from ai.src.remind_ai.data.group_split import (
    GroupSplitError,
    dataset_structure_statistics,
    select_group_safe_split,
    split_leakage_statistics,
)
from ai.src.remind_ai.data.private_split_assignment import (
    PrivateSplitAssignmentError,
    write_private_split_assignment,
)
from ai.src.remind_ai.models.tfidf_baseline import (
    BaselineConfig,
    BaselineError,
    baseline_configs,
    evaluate_model,
    fit_model,
)


class TrainingFailure(RuntimeError):
    """A caller-safe error that never contains source values or input paths."""


SOURCE_FINE_LABEL_SET = "source-fine"
TFIDF_V2_MODEL_VERSION = "tfidf-logreg-remind-coarse-v2"
PRIVATE_SPLIT_RELATIVE_PATH = Path("private") / "split_assignment.json"


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
            except OSError:
                pass
        raise TrainingFailure(
            "a baseline output JSON file could not be written safely"
        ) from exc


def _write_readme(path: Path, *, label_set: str) -> None:
    v2_notice = (
        """

This run uses the deterministic `remind-coarse-v2` fine-label policy. The exact common split
assignment is stored under `private/` and contains source identifiers and text
digests. Never publish or package that private directory.
"""
        if label_set == REMIND_COARSE_V2
        else ""
    )
    content = f"""# TF-IDF baseline output

The top-level JSON and Markdown reports contain only aggregate metrics and safe
configuration. They intentionally exclude source dialogue, talk-id, profile-id,
record-level predictions, hashes, and digests. The fitted `model.joblib` and
`vectorizer.joblib` are local model artifacts, not automatically shareable:
TF-IDF vocabulary can reveal source-derived tokens.

`validation_metrics.json` selects a model by internal validation macro-F1.
`test_metrics.json` is the one-time internal test result for that selection.
`official_validation_metrics.json` is a reference-only measurement from the
official files and must not be described as final generalization performance,
because the official split has known profile overlap and raw talk-id reuse.
Raw talk-id overlap is a non-blocking reference statistic; split isolation is
validated with profile-id and the (profile-id, talk-id) conversation key.
{v2_notice}"""
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
    except Exception:  # noqa: BLE001 - diagnostics must not replace the primary failure
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


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
    return ordered[index]


def _benchmark_inference(
    fitted: Any,
    samples: Sequence[EmotionSample],
    *,
    warmup_runs: int = 3,
    measured_runs: int = 20,
) -> dict[str, object]:
    if not samples or warmup_runs < 0 or measured_runs < 1:
        raise TrainingFailure("the inference benchmark configuration is invalid")
    batches: list[dict[str, object]] = []
    for requested_size in (1, 8, 32):
        selected = list(samples[: min(requested_size, len(samples))])
        texts = [sample.text for sample in selected]

        def predict(batch_texts: Sequence[str]) -> None:
            features = fitted.vectorizer.transform(batch_texts)
            fitted.model.predict(features)

        for _ in range(warmup_runs):
            predict(texts)
        timings_ms: list[float] = []
        for _ in range(measured_runs):
            started = time.perf_counter()
            predict(texts)
            timings_ms.append((time.perf_counter() - started) * 1_000)
        total_seconds = sum(timings_ms) / 1_000
        batches.append(
            {
                "requested_batch_size": requested_size,
                "effective_batch_size": len(selected),
                "warmup_runs": warmup_runs,
                "measured_runs": measured_runs,
                "p50_latency_ms": round(_percentile(timings_ms, 0.50), 6),
                "p95_latency_ms": round(_percentile(timings_ms, 0.95), 6),
                "samples_per_second": round(
                    len(selected) * measured_runs / max(total_seconds, 1e-12), 3
                ),
            }
        )
    return {
        "protocol_version": "emotion-inference-benchmark-v1",
        "device": "cpu",
        "vectorization_included": True,
        "source_text_or_identifiers_serialized": False,
        "batches": batches,
    }


def _evaluation_summary(
    validation_metrics: Mapping[str, object],
    test_metrics: Mapping[str, object],
    train_samples: Sequence[EmotionSample],
) -> dict[str, object]:
    validation_macro = validation_metrics.get("macro_f1")
    test_macro = test_metrics.get("macro_f1")
    per_class = test_metrics.get("per_class")
    if (
        not isinstance(validation_macro, (int, float))
        or not isinstance(test_macro, (int, float))
        or not isinstance(per_class, Mapping)
    ):
        raise TrainingFailure("evaluation summary metrics are invalid")
    train_counts = Counter(sample.label for sample in train_samples)
    minimum = min(train_counts.values())
    minority_labels = sorted(
        label for label, count in train_counts.items() if count == minimum
    )
    return {
        "selection_metric": "validation_macro_f1",
        "selection_locked_before_internal_test": True,
        "validation_macro_f1": float(validation_macro),
        "test_macro_f1": float(test_macro),
        "test_minus_validation_macro_f1": round(
            float(test_macro) - float(validation_macro), 6
        ),
        "absolute_validation_test_macro_f1_gap": round(
            abs(float(test_macro) - float(validation_macro)), 6
        ),
        "minority_class_definition": "minimum_train_support",
        "minority_train_support": minimum,
        "minority_classes": {label: per_class.get(label) for label in minority_labels},
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
    label_set: str = SOURCE_FINE_LABEL_SET,
    label_mapping_path: Path | None = None,
    label_policy_path: Path | None = None,
    annotation_manifest_path: Path | None = None,
    dataset_release_id: str | None = None,
) -> dict[str, object]:
    """Run candidate group split, validation selection, and one internal test."""

    if label_set != REMIND_COARSE_V2 and annotation_manifest_path is not None:
        raise TrainingFailure(
            "an annotation manifest may only be used with remind-coarse-v2"
        )
    if label_set != REMIND_COARSE_V2 and dataset_release_id is not None:
        raise TrainingFailure(
            "dataset_release_id may only be used with remind-coarse-v2"
        )
    run_started = time.perf_counter()
    source_official_train = load_json_samples(train_json, "official_train")
    source_official_validation = load_json_samples(
        validation_json, "official_validation"
    )
    source_samples = [*source_official_train, *source_official_validation]
    if not source_samples:
        raise TrainingFailure("the combined approved dataset is empty")
    if len({sample.label for sample in source_samples}) < 2:
        raise TrainingFailure("at least two emotion.type classes are required")
    policy = None
    manifest = None
    preparation_report: Mapping[str, object] | None = None
    samples = source_samples
    label_classes: Sequence[str] = sorted({sample.label for sample in samples})
    if label_set == REMIND_COARSE_V2:
        if (
            label_mapping_path is None
            or label_policy_path is None
        ):
            raise TrainingFailure("coarse v2 inputs are incomplete")
        if dataset_release_id is None:
            raise TrainingFailure("coarse v2 requires a dataset release id")
        dataset_release_id = validate_dataset_release_id(dataset_release_id)
        mapping = load_emotion_label_mapping(label_mapping_path)
        policy = load_emotion_label_policy_v2(label_policy_path)
        if annotation_manifest_path is not None:
            manifest = load_annotation_manifest(annotation_manifest_path, policy)
        prepared = prepare_remind_coarse_v2(
            source_samples,
            mapping,
            policy,
            manifest,
            dataset_release_id=dataset_release_id,
        )
        samples = list(prepared.samples)
        preparation_report = prepared.report
        label_classes = policy.labels
    elif label_set != SOURCE_FINE_LABEL_SET:
        raise TrainingFailure("the requested label set is unsupported")

    official_train = [
        sample for sample in samples if sample.official_split == "official_train"
    ]
    official_validation = [
        sample for sample in samples if sample.official_split == "official_validation"
    ]
    if not official_train or not official_validation:
        raise TrainingFailure("the prepared official subsets must not be empty")
    try:
        split = select_group_safe_split(
            samples,
            random_state=random_state,
            candidate_count=candidate_count,
            require_evaluation_class_coverage=label_set == REMIND_COARSE_V2,
            require_normalized_text_isolation=label_set == REMIND_COARSE_V2,
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
    blocking_overlap = {
        "profile_id_overlap_count",
        "conversation_key_overlap_count",
    }
    if label_set == REMIND_COARSE_V2:
        blocking_overlap.add("normalized_text_overlap_count")
    for name in blocking_overlap:
        counts = overlap.get(name)
        if not isinstance(counts, Mapping) or any(
            value != 0 for value in counts.values()
        ):
            raise TrainingFailure(
                "the selected internal split did not satisfy leakage isolation"
            )

    experiments: dict[str, object] = {}
    fitted_by_name: dict[str, Any] = {}
    for config in baseline_configs(
        min_df=min_df,
        max_features=max_features,
        random_state=random_state,
        include_combined=include_combined,
    ):
        experiment_started = time.perf_counter()
        fitted = fit_model(split_samples["train"], config)
        fitted_by_name[config.name] = fitted
        validation_metrics = evaluate_model(fitted, split_samples["validation"])
        experiments[config.name] = {
            "config": {
                "mode": config.mode,
                "min_df": config.min_df,
                "max_features": config.max_features,
                "random_state": config.random_state,
                "max_iter": config.max_iter,
            },
            "metrics": validation_metrics,
            "elapsed_seconds": round(time.perf_counter() - experiment_started, 6),
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
    model_selection_elapsed_seconds = time.perf_counter() - run_started
    selected_experiment = experiments[selected_name]
    assert isinstance(selected_experiment, Mapping)
    selected_validation_metrics = selected_experiment.get("metrics")
    if not isinstance(selected_validation_metrics, Mapping):
        raise TrainingFailure("the selected validation metrics are invalid")
    selected_test_metrics = evaluate_model(selected, split_samples["test"])
    validation_output = {
        "selection_metric": "macro_f1",
        "selected_model": selected_name,
        "experiments": experiments,
    }
    test_output = {
        "selected_model": selected_name,
        "selection_was_completed_before_internal_test": True,
        "evaluated_once_after_model_selection": True,
        "metrics": selected_test_metrics,
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
        "train": len(source_official_train),
        "validation": len(source_official_validation),
    }
    summary["prepared_official_record_counts"] = {
        "train": len(official_train),
        "validation": len(official_validation),
    }
    summary["label_set_version"] = label_set
    summary["strict_evaluation_class_coverage"] = label_set == REMIND_COARSE_V2
    summary["strict_normalized_text_isolation"] = label_set == REMIND_COARSE_V2

    output_dir.mkdir(parents=True, exist_ok=True)
    if label_set == REMIND_COARSE_V2:
        write_private_split_assignment(
            (output_dir / PRIVATE_SPLIT_RELATIVE_PATH).resolve(),
            samples,
            split,
            label_set_version=REMIND_COARSE_V2,
            random_state=random_state,
            candidate_count=candidate_count,
        )
        summary["private_split_assignment_written"] = True
        summary["private_split_assignment_shareable"] = False
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
            "label_field": (
                "deterministic_remind_coarse_v2"
                if label_set == REMIND_COARSE_V2
                else "$.profile.emotion.type"
            ),
            "label_set_version": label_set,
            "classes": list(label_classes),
        },
    )
    annotation_revision = manifest.annotation_revision if manifest is not None else None
    model_version = (
        TFIDF_V2_MODEL_VERSION
        if label_set == REMIND_COARSE_V2
        else "tfidf-logreg-source-fine-v1"
    )
    _write_json(
        output_dir / "run_config.json",
        {
            "model_version": model_version,
            "label_set_version": label_set,
            "dataset_release_id": dataset_release_id,
            "annotation_revision": annotation_revision,
            "label_field": (
                "deterministic_remind_coarse_v2"
                if label_set == REMIND_COARSE_V2
                else "$.profile.emotion.type"
            ),
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
            "split_random_state": random_state,
            "candidate_count": candidate_count,
            "min_df": min_df,
            "max_features": max_features,
            "official_validation_scope": "reference_only_not_final_generalization",
            "common_private_split_assignment": (
                PRIVATE_SPLIT_RELATIVE_PATH.as_posix()
                if label_set == REMIND_COARSE_V2
                else None
            ),
            "annotation_manifest_serialized": False,
        },
    )
    if policy is not None and preparation_report is not None:
        _write_json(
            output_dir / "label_policy_summary.json",
            safe_policy_payload(policy),
        )
        _write_json(
            output_dir / "preparation_report.json",
            dict(preparation_report),
        )
    inference_benchmark = _benchmark_inference(selected, split_samples["test"])
    evaluation_summary = _evaluation_summary(
        selected_validation_metrics,
        selected_test_metrics,
        split_samples["train"],
    )
    _write_json(output_dir / "inference_benchmark.json", inference_benchmark)
    _write_json(output_dir / "evaluation_summary.json", evaluation_summary)
    confusion = selected_test_metrics.get("confusion_matrix")
    per_class = selected_test_metrics.get("per_class")
    if not isinstance(confusion, Mapping) or not isinstance(per_class, Mapping):
        raise TrainingFailure("the selected test report is invalid")
    _write_json(output_dir / "confusion_matrix.json", dict(confusion))
    _write_json(
        output_dir / "classification_report.json",
        {
            "per_class": dict(per_class),
            "accuracy": selected_test_metrics.get("accuracy"),
            "macro_f1": selected_test_metrics.get("macro_f1"),
            "weighted_f1": selected_test_metrics.get("weighted_f1"),
            "sample_count": selected_test_metrics.get("sample_count"),
        },
    )
    total_elapsed_seconds = time.perf_counter() - run_started
    _write_json(
        output_dir / "training_summary.json",
        {
            "model_version": model_version,
            "selection_metric": "validation_macro_f1",
            "selected_model": selected_name,
            "total_elapsed_seconds": round(total_elapsed_seconds, 6),
            "model_selection_elapsed_seconds": round(
                model_selection_elapsed_seconds, 6
            ),
            "experiment_elapsed_seconds": {
                name: value.get("elapsed_seconds")
                for name, value in experiments.items()
                if isinstance(value, Mapping)
            },
        },
    )
    _write_json(
        output_dir / "model_metadata.json",
        {
            "artifact_schema_version": 1,
            "task": "single_label_emotion_classification",
            "model_family": "tfidf_logistic_regression",
            "model_version": model_version,
            "label_set_version": label_set,
            "labels": list(label_classes),
            "dataset_release_id": dataset_release_id,
            "annotation_revision": annotation_revision,
            "selected_by": "validation_macro_f1",
            "internal_test_evaluated_after_selection": True,
            "private_split_assignment_relative_path": (
                PRIVATE_SPLIT_RELATIVE_PATH.as_posix()
                if label_set == REMIND_COARSE_V2
                else None
            ),
            "private_split_assignment_shareable": False,
        },
    )
    _save_artifacts(output_dir, selected)
    _write_readme(output_dir / "README.md", label_set=label_set)
    return {
        "selected_model": selected_name,
        "label_set_version": label_set,
        "split_summary": summary,
        "total_elapsed_seconds": total_elapsed_seconds,
    }


def _validate_paths(
    train_json: Path,
    validation_json: Path,
    output_dir: Path,
    *,
    label_set: str,
    label_mapping_path: Path,
    label_policy_path: Path,
    annotation_manifest_path: Path | None,
    dataset_release_id: str | None,
) -> None:
    required = [train_json, validation_json, output_dir]
    if label_set != REMIND_COARSE_V2 and annotation_manifest_path is not None:
        raise TrainingFailure(
            "an annotation manifest may only be used with remind-coarse-v2"
        )
    if label_set != REMIND_COARSE_V2 and dataset_release_id is not None:
        raise TrainingFailure(
            "dataset_release_id may only be used with remind-coarse-v2"
        )
    if label_set == REMIND_COARSE_V2:
        required.extend((label_mapping_path, label_policy_path))
        if dataset_release_id is None:
            raise TrainingFailure("coarse v2 requires a dataset release id")
        validate_dataset_release_id(dataset_release_id)
        if annotation_manifest_path is not None:
            required.append(annotation_manifest_path)
    if not all(path.is_absolute() for path in required):
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
    if label_set == REMIND_COARSE_V2:
        for path in (label_mapping_path, label_policy_path):
            if not path.is_file() or path.suffix.casefold() != ".json":
                raise TrainingFailure("a required coarse v2 JSON file is unavailable")
        if annotation_manifest_path is not None and (
            not annotation_manifest_path.is_file()
            or annotation_manifest_path.suffix.casefold() != ".json"
        ):
            raise TrainingFailure("a coarse v2 annotation manifest is unavailable")


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
    parser.add_argument(
        "--label-set",
        choices=(SOURCE_FINE_LABEL_SET, REMIND_COARSE_V2),
        default=SOURCE_FINE_LABEL_SET,
    )
    parser.add_argument(
        "--label-mapping-path",
        default=str(AI_SERVICE_ROOT / "config" / "emotion_label_mapping.json"),
    )
    parser.add_argument(
        "--label-policy-path",
        default=str(AI_SERVICE_ROOT / "config" / "emotion_label_policy_v2.json"),
    )
    parser.add_argument("--annotation-manifest")
    parser.add_argument("--dataset-release-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        arguments = parser.parse_args(argv)
        train_json = Path(arguments.train_json)
        validation_json = Path(arguments.validation_json)
        output_dir = Path(arguments.output_dir)
        label_mapping_path = Path(arguments.label_mapping_path)
        label_policy_path = Path(arguments.label_policy_path)
        annotation_manifest_path = (
            Path(arguments.annotation_manifest)
            if arguments.annotation_manifest is not None
            else None
        )
        _validate_paths(
            train_json,
            validation_json,
            output_dir,
            label_set=arguments.label_set,
            label_mapping_path=label_mapping_path,
            label_policy_path=label_policy_path,
            annotation_manifest_path=annotation_manifest_path,
            dataset_release_id=arguments.dataset_release_id,
        )
        train_baseline(
            train_json=train_json,
            validation_json=validation_json,
            output_dir=output_dir,
            random_state=arguments.random_state,
            candidate_count=arguments.candidate_count,
            min_df=arguments.min_df,
            max_features=arguments.max_features,
            include_combined=arguments.include_combined,
            label_set=arguments.label_set,
            label_mapping_path=label_mapping_path,
            label_policy_path=label_policy_path,
            annotation_manifest_path=annotation_manifest_path,
            dataset_release_id=arguments.dataset_release_id,
        )
    except (
        TrainingFailure,
        DatasetValidationError,
        GroupSplitError,
        BaselineError,
        EmotionLabelMappingError,
        EmotionTaxonomyV2Error,
        PrivateSplitAssignmentError,
    ) as exc:
        print(f"TF-IDF baseline failed: {exc}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - return a caller-safe CLI error
        print(
            "TF-IDF baseline failed because of an unexpected local processing error",
            file=sys.stderr,
        )
        return 2
    print("TF-IDF baseline completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
