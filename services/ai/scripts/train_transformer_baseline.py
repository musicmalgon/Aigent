"""Train a leakage-safe KLUE-RoBERTa emotion classification baseline locally."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, NoReturn


AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = AI_SERVICE_ROOT.parent
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

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
from ai.src.remind_ai.data.emotion_label_mapping import (  # noqa: E402
    EmotionLabelMapping,
    EmotionLabelMappingError,
    load_emotion_label_mapping,
    map_samples_to_coarse,
    mapping_validation_report,
)
from ai.src.remind_ai.data.transformer_dataset import (  # noqa: E402
    TokenizedEmotionDataset,
    TransformerDatasetError,
    build_label_encoding,
    safe_batch_shape,
)
from ai.src.remind_ai.models.transformer_classifier import (  # noqa: E402
    TransformerModelConfig,
    TransformerModelError,
    comparison_payload,
    create_data_collator,
    load_classifier,
    load_tokenizer,
    select_device,
)
from ai.src.remind_ai.training.transformer_trainer import (  # noqa: E402
    TrainingConfig,
    TransformerTrainingError,
    evaluate,
    evaluate_with_predictions,
    evaluation_already_completed,
    fit,
    make_dataloader,
    seed_everything,
)
from ai.src.remind_ai.training.progress import (  # noqa: E402
    ProgressConfig,
    ProgressReporter,
    format_duration,
)
from ai.src.emotion.coarse_settings import TRAINING_MAX_LENGTH  # noqa: E402


class TransformerBaselineFailure(RuntimeError):
    """A caller-safe error that never contains source values, IDs, or paths."""


def _read_json(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransformerBaselineFailure("a required baseline JSON file is invalid") from exc
    if not isinstance(payload, Mapping):
        raise TransformerBaselineFailure("a required baseline JSON file is invalid")
    return payload


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".transformer-baseline-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
    except Exception as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise TransformerBaselineFailure("a baseline output could not be written safely") from exc


def _write_text(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".transformer-baseline-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(path)
    except Exception as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise TransformerBaselineFailure("a baseline text output could not be written safely") from exc


def _write_predictions(
    path: Path,
    expected: Sequence[int],
    predicted: Sequence[int],
    labels: Any,
) -> None:
    lines = [
        json.dumps(
            {
                "sample_index": index,
                "true_label_id": expected_id,
                "true_label": labels.id2label[expected_id],
                "predicted_label_id": predicted_id,
                "predicted_label": labels.id2label[predicted_id],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for index, (expected_id, predicted_id) in enumerate(zip(expected, predicted, strict=True))
    ]
    _write_text(path, "\n".join(lines) + "\n")


def _class_counts(samples: Sequence[EmotionSample]) -> dict[str, int]:
    return dict(sorted(Counter(sample.label for sample in samples).items()))


def _split_summary(
    samples: Sequence[EmotionSample],
    split_samples: Mapping[str, Sequence[EmotionSample]],
    split: Any,
) -> dict[str, object]:
    all_classes = {sample.label for sample in samples}
    summary = {
        "dataset": dataset_structure_statistics(samples),
        "splits": {
            name: {
                "record_count": len(partition),
                "profile_count": len({sample.group_id for sample in partition}),
                "class_counts": _class_counts(partition),
                "missing_classes": sorted(
                    all_classes - {sample.label for sample in partition}
                ),
            }
            for name, partition in split_samples.items()
        },
        "overlap_checks": split_leakage_statistics(dict(split_samples)),
        "candidate_seed": split.candidate_seed,
        "balance_score": split.balance_score,
        "random_state": None,
        "candidate_count": split.evaluated_candidate_count,
        "fallback_used": split.fallback_used,
    }
    return summary


def _tfidf_split_config(tfidf_dir: Path) -> tuple[int, int, Mapping[str, object]]:
    run_config = _read_json(tfidf_dir / "run_config.json")
    split_summary = _read_json(tfidf_dir / "split_summary.json")
    random_state = run_config.get("random_state")
    candidate_count = run_config.get("candidate_count")
    if not isinstance(random_state, int) or not isinstance(candidate_count, int):
        raise TransformerBaselineFailure("TF-IDF split configuration is unavailable")
    return random_state, candidate_count, split_summary


def _safe_split_signature(summary: Mapping[str, object]) -> dict[str, object]:
    dataset = summary.get("dataset")
    splits = summary.get("splits")
    if not isinstance(dataset, Mapping) or not isinstance(splits, Mapping):
        raise TransformerBaselineFailure("TF-IDF split summary is invalid")
    compact_splits: dict[str, object] = {}
    for name in ("train", "validation", "test"):
        value = splits.get(name)
        if not isinstance(value, Mapping):
            raise TransformerBaselineFailure("TF-IDF split summary is invalid")
        compact_splits[name] = {
            "record_count": value.get("record_count"),
            "profile_count": value.get("profile_count"),
            "class_counts": value.get("class_counts"),
            "missing_classes": value.get("missing_classes"),
        }
    return {
        "dataset": {
            "record_count": dataset.get("record_count"),
            "profile_count": dataset.get("profile_count"),
            "class_count": dataset.get("class_count"),
            "class_record_counts": dataset.get("class_record_counts"),
        },
        "splits": compact_splits,
        "candidate_seed": summary.get("candidate_seed"),
    }


def _reproduce_split(
    samples: Sequence[EmotionSample], tfidf_dir: Path
) -> tuple[Any, dict[str, list[EmotionSample]], dict[str, object], int, int]:
    random_state, candidate_count, expected = _tfidf_split_config(tfidf_dir)
    split = select_group_safe_split(
        samples, random_state=random_state, candidate_count=candidate_count
    )
    split_samples = {
        name: split.samples_for(samples, name)
        for name in ("train", "validation", "test")
    }
    summary = _split_summary(samples, split_samples, split)
    summary["random_state"] = random_state
    summary["requested_candidate_count"] = candidate_count
    if _safe_split_signature(summary) != _safe_split_signature(expected):
        raise TransformerBaselineFailure(
            "the deterministic split does not match the TF-IDF baseline"
        )
    overlap = summary["overlap_checks"]
    assert isinstance(overlap, Mapping)
    for name in (
        "profile_id_overlap_count",
        "conversation_key_overlap_count",
        "normalized_text_overlap_count",
    ):
        counts = overlap.get(name)
        if not isinstance(counts, Mapping) or any(value != 0 for value in counts.values()):
            raise TransformerBaselineFailure(
                "the reproduced split failed leakage validation"
            )
    all_classes = {sample.label for sample in samples}
    if {sample.label for sample in split_samples["train"]} != all_classes:
        raise TransformerBaselineFailure("the reproduced train split is missing classes")
    return split, split_samples, summary, random_state, candidate_count


def _tfidf_reference(tfidf_dir: Path) -> tuple[str, Mapping[str, object]]:
    validation = _read_json(tfidf_dir / "validation_metrics.json")
    test = _read_json(tfidf_dir / "test_metrics.json")
    selected = validation.get("selected_model")
    metrics = test.get("metrics")
    if not isinstance(selected, str) or not isinstance(metrics, Mapping):
        raise TransformerBaselineFailure("TF-IDF comparison metrics are invalid")
    return selected, metrics


def _fine_transformer_reference() -> Mapping[str, object] | None:
    metrics_path = (
        AI_SERVICE_ROOT
        / "data"
        / "outputs"
        / "transformer-baseline"
        / "test_metrics.json"
    )
    if not metrics_path.is_file():
        return None
    payload = _read_json(metrics_path)
    metrics = payload.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    required = ("accuracy", "macro_f1", "weighted_f1", "sample_count")
    if not all(isinstance(metrics.get(name), (int, float)) for name in required):
        return None
    return metrics


def _fine_coarse_comparison(
    coarse_metrics: Mapping[str, object] | None,
) -> dict[str, object]:
    fine_metrics = _fine_transformer_reference()
    return {
        "warning": (
            "Fine-grained and coarse-grained tasks have different label spaces and "
            "are not directly equivalent."
        ),
        "fine": (
            {
                "num_classes": 60,
                "accuracy": fine_metrics.get("accuracy"),
                "macro_f1": fine_metrics.get("macro_f1"),
                "weighted_f1": fine_metrics.get("weighted_f1"),
                "sample_count": fine_metrics.get("sample_count"),
            }
            if fine_metrics is not None
            else None
        ),
        "coarse": {
            "num_classes": 6,
            "accuracy": coarse_metrics.get("accuracy") if coarse_metrics else None,
            "macro_f1": coarse_metrics.get("macro_f1") if coarse_metrics else None,
            "weighted_f1": coarse_metrics.get("weighted_f1") if coarse_metrics else None,
            "sample_count": coarse_metrics.get("sample_count") if coarse_metrics else None,
        },
    }


def _coarse_experiment_summary(
    comparison: Mapping[str, object], *, dry_run: bool
) -> str:
    status = (
        "This directory contains preflight artifacts only; no final metrics were produced."
        if dry_run
        else "Metrics were produced from the best validation macro-F1 checkpoint."
    )
    fine_available = comparison.get("fine") is not None
    return f"""# Transformer coarse emotion baseline

{status}

## Purpose

The fine baseline distinguishes 60 nuanced AI Hub emotion labels. This separate
baseline predicts six service-oriented categories: 기쁨, 불안, 당황, 분노, 슬픔,
and 상처. The tasks have different label spaces and their scores are not directly
equivalent; a higher coarse score must not be described as a simple improvement.

The mapping is derived from the official AI Hub source workbook fields
`감정_대분류` and `감정_소분류`, joined to every JSON record through normalized
HS01/HS02/HS03. The audited mapping covered all 58,268 records with no unmatched
or ambiguous records.

## Evaluation policy

The deterministic profile-safe TF-IDF split is reproduced before labels are
mapped. Profile, conversation-key, and normalized-text overlap remain zero.
Validation macro-F1 selects the checkpoint; internal test is evaluated once only
after selection. Existing fine output is read-only and was
{"available" if fine_available else "not available"} for the comparison artifact.

## Safety

Only HS01, HS02, and optional HS03 are model inputs. System responses and metadata
are excluded. Predictions contain sequential indices and labels only, never source
text or identifiers. This experimental classifier is not a medical diagnosis.
"""


def _run_config_payload(
    arguments: argparse.Namespace, selection: Any, *, num_labels: int
) -> dict[str, object]:
    return {
        "model_name": arguments.model_name,
        "model_version": f"klue-roberta-{arguments.label_level}-v1",
        "label_level": arguments.label_level,
        "num_labels": num_labels,
        "label_field": "$.profile.emotion.type",
        "label_mapping": (
            "services/ai/config/emotion_label_mapping.json"
            if arguments.label_level == "coarse"
            else None
        ),
        "input_fields": [
            "$.talk.content.HS01",
            "$.talk.content.HS02",
            "$.talk.content.HS03",
        ],
        "system_response_fields_included": False,
        "metadata_features_included": False,
        "train_json_provided": True,
        "validation_json_provided": True,
        "tfidf_output_available": True,
        "output_directory_created": True,
        "max_length": arguments.max_length,
        "epochs": arguments.epochs,
        "learning_rate": arguments.learning_rate,
        "train_batch_size": arguments.train_batch_size,
        "eval_batch_size": arguments.eval_batch_size,
        "gradient_accumulation_steps": arguments.gradient_accumulation_steps,
        "effective_train_batch_size": (
            arguments.train_batch_size * arguments.gradient_accumulation_steps
        ),
        "weight_decay": arguments.weight_decay,
        "warmup_ratio": arguments.warmup_ratio,
        "max_grad_norm": arguments.max_grad_norm,
        "early_stopping_patience": arguments.early_stopping_patience,
        "random_state": arguments.random_state,
        "device_requested": selection.requested,
        "device_selected": selection.selected,
        "cpu_fallback_used": selection.cpu_fallback_used,
        "fp16_enabled": selection.fp16_enabled,
        "num_workers": arguments.num_workers,
        "dry_run": arguments.dry_run,
        "progress_bar_enabled": not arguments.disable_progress_bar,
        "progress_update_interval": arguments.progress_update_interval,
        "show_gpu_memory": arguments.show_gpu_memory,
        "log_every_n_steps": arguments.log_every_n_steps,
        "resume_from_checkpoint": arguments.resume_from_checkpoint is not None,
        "official_validation_scope": "reference_only_not_final_generalization",
    }


def _write_readme(path: Path, dry_run: bool, label_level: str) -> None:
    status = "Dry-run preflight only; no training metrics were produced." if dry_run else (
        "The best model was selected with internal validation macro-F1."
    )
    content = f"""# Transformer {label_level} baseline output

{status}

This directory intentionally excludes source dialogue, profile-id, talk-id,
conversation keys, hashes, digests, and input paths.
Internal test macro-F1 is the leakage-safe primary result. Official Validation
is reference-only because the official files have known group overlap. This
emotion classifier is an experimental non-medical signal and is not a diagnosis.
"""
    _write_text(path, content)


def _save_final_artifacts(model: Any, tokenizer: Any, output_dir: Path) -> None:
    try:
        model.save_pretrained(output_dir / "model")
        tokenizer.save_pretrained(output_dir / "tokenizer")
    except Exception as exc:
        raise TransformerBaselineFailure("final model artifacts could not be saved") from exc


def _validate_paths(arguments: argparse.Namespace) -> None:
    required = [
        Path(arguments.train_json),
        Path(arguments.validation_json),
        Path(arguments.tfidf_output_dir),
        Path(arguments.output_dir),
    ]
    if arguments.resume_from_checkpoint is not None:
        required.append(Path(arguments.resume_from_checkpoint))
    if arguments.label_level == "coarse":
        required.append(Path(arguments.label_mapping_path))
    if not all(path.is_absolute() for path in required):
        raise TransformerBaselineFailure("all input and output paths must be absolute")
    train_json, validation_json, tfidf_dir, _ = required[:4]
    if not train_json.is_file() or not validation_json.is_file():
        raise TransformerBaselineFailure("a required JSON input is unavailable")
    if train_json.suffix.casefold() != ".json" or validation_json.suffix.casefold() != ".json":
        raise TransformerBaselineFailure("both dataset inputs must be JSON files")
    if train_json.resolve() == validation_json.resolve():
        raise TransformerBaselineFailure("dataset inputs must be separate files")
    if not tfidf_dir.is_dir():
        raise TransformerBaselineFailure("the TF-IDF output directory is unavailable")
    if arguments.label_level == "coarse":
        if arguments.max_length != TRAINING_MAX_LENGTH:
            raise TransformerBaselineFailure(
                "coarse mode max-length must be 128 to match the inference contract"
            )
        mapping_path = Path(arguments.label_mapping_path)
        if not mapping_path.is_file() or mapping_path.suffix.casefold() != ".json":
            raise TransformerBaselineFailure("the coarse label mapping file is unavailable")
        fine_output = AI_SERVICE_ROOT / "data" / "outputs" / "transformer-baseline"
        if Path(arguments.output_dir).resolve() == fine_output.resolve():
            raise TransformerBaselineFailure(
                "coarse mode cannot write to the fine transformer output directory"
            )
    if Path(arguments.model_name).is_absolute():
        raise TransformerBaselineFailure("model-name must be a public model identifier")
    if (
        arguments.resume_from_checkpoint is not None
        and not Path(arguments.resume_from_checkpoint).is_dir()
    ):
        raise TransformerBaselineFailure("the resume checkpoint is unavailable")


def run(arguments: argparse.Namespace) -> dict[str, object]:
    run_started = time.perf_counter()
    _validate_paths(arguments)
    train_path = Path(arguments.train_json)
    validation_path = Path(arguments.validation_json)
    tfidf_dir = Path(arguments.tfidf_output_dir)
    requested_output_dir = Path(arguments.output_dir)
    output_dir = (
        requested_output_dir / "dry-run"
        if arguments.dry_run and arguments.label_level == "coarse"
        else requested_output_dir
    )
    state_path = output_dir / "evaluation_state.json"
    if (
        not arguments.dry_run
        and evaluation_already_completed(state_path)
        and not arguments.force_evaluate
    ):
        raise TransformerBaselineFailure(
            "final evaluation already completed; use --force-evaluate to repeat it"
        )
    official_train = load_json_samples(train_path, "official_train")
    official_validation = load_json_samples(validation_path, "official_validation")
    samples = [*official_train, *official_validation]
    if not samples:
        raise TransformerBaselineFailure("the combined approved dataset is empty")
    split, fine_split_samples, fine_split_summary, split_random_state, candidate_count = _reproduce_split(
        samples, tfidf_dir
    )
    if arguments.random_state != split_random_state:
        raise TransformerBaselineFailure(
            "random_state must match the TF-IDF split configuration"
        )
    mapping: EmotionLabelMapping | None = None
    mapping_report: dict[str, object] | None = None
    model_samples = samples
    split_samples = fine_split_samples
    split_summary = fine_split_summary
    if arguments.label_level == "coarse":
        mapping_path = Path(arguments.label_mapping_path)
        mapping = load_emotion_label_mapping(mapping_path)
        model_samples = map_samples_to_coarse(
            samples, mapping, mapping_path=mapping_path
        )
        split_samples = {
            name: map_samples_to_coarse(
                partition, mapping, mapping_path=mapping_path
            )
            for name, partition in fine_split_samples.items()
        }
        split_summary = _split_summary(model_samples, split_samples, split)
        split_summary["random_state"] = split_random_state
        split_summary["requested_candidate_count"] = candidate_count
        split_summary["fine_split_signature_verified_before_mapping"] = True
        split_summary["fine_record_count"] = len(samples)
        mapping_report = mapping_validation_report(mapping, samples, split_samples)
        if not mapping_report["sample_count_preserved"]:
            raise TransformerBaselineFailure("coarse mapping changed the split sample count")
    labels = build_label_encoding(
        model_samples,
        classes=(mapping.coarse_labels if mapping is not None else None),
    )
    model_official_validation = model_samples[len(official_train) :]
    selection = select_device(
        arguments.device,
        allow_cpu_fallback=arguments.allow_cpu_fallback,
        fp16_requested=arguments.fp16,
    )
    if selection.selected == "cpu":
        print(
            "Transformer baseline warning: CPU execution is supported but may be slow",
            file=sys.stderr,
        )
    if selection.cpu_fallback_used:
        print(
            "Transformer baseline warning: the requested accelerator fell back to CPU",
            file=sys.stderr,
        )
    try:
        torch = importlib.import_module("torch")
    except ImportError as exc:
        raise TransformerBaselineFailure("PyTorch is required for this baseline") from exc
    seed_everything(torch, arguments.random_state)
    model_source = arguments.resume_from_checkpoint or arguments.model_name
    tokenizer = load_tokenizer(model_source)
    model = load_classifier(
        TransformerModelConfig(model_name=model_source, max_length=arguments.max_length),
        labels,
    )
    collator = create_data_collator(tokenizer)
    output_dir.mkdir(parents=True, exist_ok=True)
    split_summary["split_reused_from_tfidf"] = True
    _write_json(output_dir / "split_summary.json", split_summary)
    _write_json(
        output_dir / "label_classes.json",
        {
            "label_field": "$.profile.emotion.type",
            "label_level": arguments.label_level,
            "classes": list(labels.classes),
            "label2id": dict(labels.label2id),
            "id2label": {str(key): value for key, value in labels.id2label.items()},
        },
    )
    _write_json(
        output_dir / "run_config.json",
        _run_config_payload(arguments, selection, num_labels=len(labels.classes)),
    )
    if mapping is not None and mapping_report is not None:
        _write_json(
            output_dir / "label_mapping.json",
            dict(_read_json(Path(arguments.label_mapping_path))),
        )
        _write_json(output_dir / "mapping_validation.json", mapping_report)
    selected_tfidf: str | None = None
    tfidf_metrics: Mapping[str, object] | None = None
    if arguments.label_level == "fine":
        selected_tfidf, tfidf_metrics = _tfidf_reference(tfidf_dir)

    if arguments.dry_run:
        limit = min(arguments.dry_run_samples, len(split_samples["train"]))
        dry_samples = split_samples["train"][:limit]
        dataset = TokenizedEmotionDataset(
            dry_samples, tokenizer, labels, max_length=arguments.max_length
        )
        loader = make_dataloader(
            torch,
            dataset,
            collator,
            batch_size=min(arguments.train_batch_size, limit),
            shuffle=False,
            num_workers=arguments.num_workers,
        )
        batch = next(iter(loader))
        device = torch.device(selection.selected)
        with tempfile.TemporaryDirectory(prefix="transformer-dry-run-") as temporary:
            smoke_training = fit(
                torch=torch,
                model=model,
                tokenizer=tokenizer,
                train_loader=loader,
                validation_loader=loader,
                labels=labels,
                device=device,
                checkpoints_dir=Path(temporary) / "checkpoints",
                config=TrainingConfig(
                    epochs=1,
                    learning_rate=arguments.learning_rate,
                    train_batch_size=min(arguments.train_batch_size, limit),
                    eval_batch_size=min(arguments.train_batch_size, limit),
                    gradient_accumulation_steps=min(
                        arguments.gradient_accumulation_steps, len(loader)
                    ),
                    weight_decay=arguments.weight_decay,
                    warmup_ratio=arguments.warmup_ratio,
                    max_grad_norm=arguments.max_grad_norm,
                    early_stopping_patience=1,
                    random_state=arguments.random_state,
                    num_workers=arguments.num_workers,
                    fp16=selection.fp16_enabled,
                    progress_bar=not arguments.disable_progress_bar,
                    progress_update_interval=arguments.progress_update_interval,
                    show_gpu_memory=arguments.show_gpu_memory,
                    log_every_n_steps=arguments.log_every_n_steps,
                ),
            )
            checkpoint_reloaded = (Path(temporary) / "checkpoints" / "best").is_dir()
        model.eval()
        with torch.no_grad():
            moved = {
                name: value.to(device) if hasattr(value, "to") else value
                for name, value in batch.items()
            }
            outputs = model(**moved)
        logits = getattr(outputs, "logits", None)
        if logits is None or int(logits.shape[-1]) != len(labels.classes):
            raise TransformerBaselineFailure("the dry-run model forward pass is invalid")
        smoke_metrics = smoke_training.history[-1]["validation_metrics"]
        _write_json(
            output_dir / "dry_run_summary.json",
            {
                "completed": True,
                "full_training_started": False,
                "smoke_backward_completed": True,
                "temporary_checkpoint_saved_and_reloaded": checkpoint_reloaded,
                "sample_count": limit,
                "batch": safe_batch_shape(batch),
                "model_forward_completed": True,
                "model_classifier_num_labels": len(labels.classes),
                "metric_function_completed": bool(smoke_metrics),
                "progress_bar_enabled": not arguments.disable_progress_bar,
            },
        )
        if arguments.label_level == "coarse":
            comparison = _fine_coarse_comparison(None)
            _write_json(output_dir / "comparison_with_fine_baseline.json", comparison)
            _write_text(
                output_dir / "experiment_summary.md",
                _coarse_experiment_summary(comparison, dry_run=True),
            )
        else:
            assert tfidf_metrics is not None and selected_tfidf is not None
            _write_json(
                output_dir / "comparison.json",
                comparison_payload(
                    None,
                    tfidf_metrics,
                    model_name=arguments.model_name,
                    selected_tfidf_model=selected_tfidf,
                ),
            )
        _write_readme(output_dir / "README.md", True, arguments.label_level)
        return {
            "dry_run": True,
            "label_level": arguments.label_level,
            "candidate_seed": split.candidate_seed,
            "output_dir": str(output_dir),
            "total_elapsed_seconds": time.perf_counter() - run_started,
        }

    datasets = {
        name: TokenizedEmotionDataset(
            partition, tokenizer, labels, max_length=arguments.max_length
        )
        for name, partition in split_samples.items()
    }
    loaders = {
        "train": make_dataloader(
            torch,
            datasets["train"],
            collator,
            batch_size=arguments.train_batch_size,
            shuffle=True,
            num_workers=arguments.num_workers,
        ),
        "validation": make_dataloader(
            torch,
            datasets["validation"],
            collator,
            batch_size=arguments.eval_batch_size,
            shuffle=False,
            num_workers=arguments.num_workers,
        ),
        "test": make_dataloader(
            torch,
            datasets["test"],
            collator,
            batch_size=arguments.eval_batch_size,
            shuffle=False,
            num_workers=arguments.num_workers,
        ),
    }
    device = torch.device(selection.selected)
    training = fit(
        torch=torch,
        model=model,
        tokenizer=tokenizer,
        train_loader=loaders["train"],
        validation_loader=loaders["validation"],
        labels=labels,
        device=device,
        checkpoints_dir=output_dir / "checkpoints",
        config=TrainingConfig(
            epochs=arguments.epochs,
            learning_rate=arguments.learning_rate,
            train_batch_size=arguments.train_batch_size,
            eval_batch_size=arguments.eval_batch_size,
            gradient_accumulation_steps=arguments.gradient_accumulation_steps,
            weight_decay=arguments.weight_decay,
            warmup_ratio=arguments.warmup_ratio,
            max_grad_norm=arguments.max_grad_norm,
            early_stopping_patience=arguments.early_stopping_patience,
            random_state=arguments.random_state,
            num_workers=arguments.num_workers,
            fp16=selection.fp16_enabled,
            progress_bar=not arguments.disable_progress_bar,
            progress_update_interval=arguments.progress_update_interval,
            show_gpu_memory=arguments.show_gpu_memory,
            log_every_n_steps=arguments.log_every_n_steps,
        ),
        resume_from_checkpoint=(
            Path(arguments.resume_from_checkpoint)
            if arguments.resume_from_checkpoint is not None
            else None
        ),
    )
    validation_metrics = training.history[training.best_epoch - 1]["validation_metrics"]
    assert isinstance(validation_metrics, Mapping)
    reporter = ProgressReporter(
        ProgressConfig(
            enabled=not arguments.disable_progress_bar,
            update_interval=arguments.progress_update_interval,
            show_gpu_memory=arguments.show_gpu_memory,
        )
    )
    test_metrics, expected_ids, predicted_ids = evaluate_with_predictions(
        torch,
        model,
        loaders["test"],
        device,
        labels,
        reporter=reporter,
        desc="Final internal test",
    )
    official_dataset = TokenizedEmotionDataset(
        model_official_validation, tokenizer, labels, max_length=arguments.max_length
    )
    official_loader = make_dataloader(
        torch,
        official_dataset,
        collator,
        batch_size=arguments.eval_batch_size,
        shuffle=False,
        num_workers=arguments.num_workers,
    )
    official_metrics = evaluate(
        torch,
        model,
        official_loader,
        device,
        labels,
        reporter=reporter,
        desc="Official Validation [Reference]",
    )
    _write_json(
        output_dir / "validation_metrics.json",
        {
            "selection_metric": "macro_f1",
            "best_epoch": training.best_epoch,
            "metrics": dict(validation_metrics),
        },
    )
    _write_json(
        output_dir / "best_validation_metrics.json",
        {
            "selection_metric": "macro_f1",
            "best_epoch": training.best_epoch,
            "metrics": dict(validation_metrics),
        },
    )
    _write_json(
        output_dir / "test_metrics.json",
        (
            {
                **test_metrics,
                "selection_was_completed_before_internal_test": True,
                "evaluated_once_after_model_selection": True,
            }
            if arguments.label_level == "coarse"
            else {
                "selection_was_completed_before_internal_test": True,
                "evaluated_once_after_model_selection": True,
                "metrics": test_metrics,
            }
        ),
    )
    _write_json(
        output_dir / "official_validation_metrics.json",
        {
            "scope": "reference_only_not_final_generalization",
            "used_for_model_selection": False,
            "metrics": official_metrics,
        },
    )
    _write_json(
        output_dir / "training_history.json",
        {
            "best_epoch": training.best_epoch,
            "best_validation_macro_f1": training.best_validation_macro_f1,
            "stopped_early": training.stopped_early,
            "optimizer_step_count": training.optimizer_step_count,
            "total_elapsed_seconds": training.total_elapsed_seconds,
            "total_elapsed_duration": format_duration(training.total_elapsed_seconds),
            "epochs": list(training.history),
        },
    )
    if arguments.label_level == "coarse":
        confusion = test_metrics.get("confusion_matrix")
        per_class = test_metrics.get("per_class")
        if not isinstance(confusion, Mapping) or not isinstance(per_class, Mapping):
            raise TransformerBaselineFailure("coarse evaluation artifacts are invalid")
        _write_json(output_dir / "confusion_matrix.json", dict(confusion))
        _write_json(
            output_dir / "classification_report.json",
            {
                "per_class": dict(per_class),
                "accuracy": test_metrics.get("accuracy"),
                "macro_precision": test_metrics.get("macro_precision"),
                "macro_recall": test_metrics.get("macro_recall"),
                "macro_f1": test_metrics.get("macro_f1"),
                "weighted_f1": test_metrics.get("weighted_f1"),
                "sample_count": test_metrics.get("sample_count"),
            },
        )
        _write_predictions(
            output_dir / "predictions.jsonl", expected_ids, predicted_ids, labels
        )
        comparison = _fine_coarse_comparison(test_metrics)
        _write_json(output_dir / "comparison_with_fine_baseline.json", comparison)
        _write_text(
            output_dir / "experiment_summary.md",
            _coarse_experiment_summary(comparison, dry_run=False),
        )
    else:
        assert tfidf_metrics is not None and selected_tfidf is not None
        _write_json(
            output_dir / "comparison.json",
            comparison_payload(
                test_metrics,
                tfidf_metrics,
                model_name=arguments.model_name,
                selected_tfidf_model=selected_tfidf,
            ),
        )
    _save_final_artifacts(model, tokenizer, output_dir)
    _write_json(
        state_path,
        {"final_evaluation_completed": True, "force_evaluate_used": arguments.force_evaluate},
    )
    _write_readme(output_dir / "README.md", False, arguments.label_level)
    return {
        "dry_run": False,
        "label_level": arguments.label_level,
        "best_epoch": training.best_epoch,
        "best_validation_macro_f1": training.best_validation_macro_f1,
        "test_accuracy": test_metrics.get("accuracy"),
        "test_macro_f1": test_metrics.get("macro_f1"),
        "test_weighted_f1": test_metrics.get("weighted_f1"),
        "output_dir": str(output_dir),
        "total_elapsed_seconds": time.perf_counter() - run_started,
    }


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise TransformerBaselineFailure("command arguments are invalid")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a nonnegative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative integer")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive number")
    return parsed


def _ratio(value: str) -> float:
    parsed = _positive_float(value)
    if parsed > 1:
        raise argparse.ArgumentTypeError("expected a ratio no greater than one")
    return parsed


def _result_number(result: Mapping[str, object], name: str) -> float:
    value = result.get(name)
    if not isinstance(value, (int, float)):
        raise TransformerBaselineFailure("a completion metric is invalid")
    return float(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Train a profile-safe KLUE-RoBERTa baseline without logging source records."
    )
    parser.add_argument("--train-json", required=True)
    parser.add_argument("--validation-json", required=True)
    parser.add_argument("--tfidf-output-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label-level", choices=("fine", "coarse"), default="fine")
    parser.add_argument(
        "--label-mapping-path",
        default=str(AI_SERVICE_ROOT / "config" / "emotion_label_mapping.json"),
    )
    parser.add_argument("--model-name", default="klue/roberta-base")
    parser.add_argument("--max-length", type=_positive_int, default=128)
    parser.add_argument("--epochs", type=_positive_int, default=3)
    parser.add_argument("--learning-rate", type=_positive_float, default=2e-5)
    parser.add_argument("--train-batch-size", type=_positive_int, default=8)
    parser.add_argument("--eval-batch-size", type=_positive_int, default=16)
    parser.add_argument("--gradient-accumulation-steps", type=_positive_int, default=2)
    parser.add_argument("--weight-decay", type=_positive_float, default=0.01)
    parser.add_argument("--warmup-ratio", type=_ratio, default=0.1)
    parser.add_argument("--max-grad-norm", type=_positive_float, default=1.0)
    parser.add_argument("--early-stopping-patience", type=_positive_int, default=2)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    parser.add_argument("--num-workers", type=_nonnegative_int, default=0)
    parser.add_argument("--allow-cpu-fallback", action="store_true")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--resume-from-checkpoint")
    parser.add_argument("--force-evaluate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dry-run-samples", type=_positive_int, default=32)
    parser.add_argument("--disable-progress-bar", action="store_true")
    parser.add_argument("--progress-update-interval", type=_positive_int, default=1)
    parser.add_argument("--show-gpu-memory", action="store_true")
    parser.add_argument("--log-every-n-steps", type=_nonnegative_int, default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _build_parser().parse_args(argv)
        result = run(arguments)
    except (
        TransformerBaselineFailure,
        DatasetValidationError,
        GroupSplitError,
        TransformerDatasetError,
        EmotionLabelMappingError,
        TransformerModelError,
        TransformerTrainingError,
    ) as exc:
        print(f"Transformer baseline failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print(
            "Transformer baseline failed because of an unexpected local processing error",
            file=sys.stderr,
        )
        return 2
    if arguments.dry_run:
        print(
            "Transformer coarse baseline dry-run completed"
            if arguments.label_level == "coarse"
            else "Transformer baseline dry-run completed"
        )
        return 0
    if arguments.label_level == "coarse":
        separator = "=" * 60
        print(separator)
        print("Transformer coarse baseline completed")
        print(separator)
        print(f"Best epoch        : {result['best_epoch']}")
        print(f"Best validation F1: {_result_number(result, 'best_validation_macro_f1'):.6f}")
        print(f"Test accuracy     : {_result_number(result, 'test_accuracy'):.6f}")
        print(f"Test macro F1     : {_result_number(result, 'test_macro_f1'):.6f}")
        print(f"Test weighted F1  : {_result_number(result, 'test_weighted_f1'):.6f}")
        print(f"Output directory  : {result['output_dir']}")
        print(
            "Total elapsed     : "
            f"{format_duration(_result_number(result, 'total_elapsed_seconds'))}"
        )
        print(separator)
    else:
        print("Transformer baseline completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
