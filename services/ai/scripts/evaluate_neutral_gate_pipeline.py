"""Evaluate cached outputs from the gate plus six-class emotion pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn

AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = AI_SERVICE_ROOT.parent
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

from ai.src.remind_ai.evaluation.neutral_gate_pipeline import (  # noqa: E402
    NeutralGatePipelineEvaluationError,
    ScoredPipelinePrediction,
    evaluate_combined_pipeline,
)


def _load(path: Path) -> list[ScoredPipelinePrediction]:
    rows: list[ScoredPipelinePrediction] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, Mapping):
                    raise NeutralGatePipelineEvaluationError(
                        "a score row must be an object"
                    )
                if set(payload) - {
                    "true_gate_label",
                    "emotional_probability",
                    "true_emotion",
                    "predicted_emotion",
                    "confidence",
                    "margin",
                    "gate_latency_ms",
                    "coarse_latency_ms",
                }:
                    raise NeutralGatePipelineEvaluationError(
                        "a score row has unsupported fields"
                    )
                rows.append(ScoredPipelinePrediction(**dict(payload)))
    except NeutralGatePipelineEvaluationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise NeutralGatePipelineEvaluationError(
            "combined pipeline scores are invalid"
        ) from exc
    return rows


def run(arguments: argparse.Namespace) -> None:
    metrics = evaluate_combined_pipeline(
        _load(Path(arguments.scores_jsonl)),
        gate_threshold=arguments.gate_threshold,
        confidence_threshold=arguments.confidence_threshold,
        margin_threshold=arguments.margin_threshold,
    )
    serialized = json.dumps(
        metrics,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    if arguments.output_json:
        Path(arguments.output_json).write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate cached neutral-gate and six-class pipeline scores."
    )
    parser.add_argument("--scores-jsonl", required=True)
    parser.add_argument("--gate-threshold", type=float, required=True)
    parser.add_argument("--confidence-threshold", type=float, default=0.65)
    parser.add_argument("--margin-threshold", type=float, default=0.15)
    parser.add_argument("--output-json")
    return parser


def _fail(message: str) -> NoReturn:
    print(f"Combined neutral gate evaluation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    try:
        run(_parser().parse_args())
    except NeutralGatePipelineEvaluationError as exc:
        _fail(str(exc))
