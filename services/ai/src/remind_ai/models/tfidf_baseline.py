"""Leakage-safe TF-IDF and Logistic Regression baseline helpers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
import importlib
from typing import Any, Literal

from ..data.emotion_dataset import EmotionSample


ModelMode = Literal["word", "char", "word_char"]


class BaselineError(ValueError):
    """Raised for invalid baseline configuration or insufficient training data."""


@dataclass(frozen=True)
class BaselineConfig:
    name: str
    mode: ModelMode
    min_df: int = 3
    max_features: int | None = None
    random_state: int = 42
    max_iter: int = 2_000


@dataclass
class FittedBaseline:
    config: BaselineConfig
    vectorizer: Any
    model: Any


def baseline_configs(
    *,
    min_df: int = 3,
    max_features: int | None = None,
    random_state: int = 42,
    include_combined: bool = False,
) -> list[BaselineConfig]:
    """Return the required word and char experiments, plus an optional union."""

    configs = [
        BaselineConfig("word_tfidf", "word", min_df, max_features, random_state),
        BaselineConfig("char_tfidf", "char", min_df, max_features, random_state),
    ]
    if include_combined:
        configs.append(
            BaselineConfig(
                "word_char_tfidf",
                "word_char",
                min_df,
                max_features,
                random_state,
            )
        )
    return configs


def _dependencies() -> tuple[Any, Any, Any]:
    try:
        tfidf_vectorizer = importlib.import_module(
            "sklearn.feature_extraction.text"
        ).TfidfVectorizer
        logistic_regression = importlib.import_module(
            "sklearn.linear_model"
        ).LogisticRegression
        feature_union = importlib.import_module("sklearn.pipeline").FeatureUnion
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise BaselineError("scikit-learn is required for the TF-IDF baseline") from exc
    return tfidf_vectorizer, logistic_regression, feature_union


def create_vectorizer(config: BaselineConfig) -> Any:
    """Create an unfitted vectorizer that has no access to IDs or labels."""

    TfidfVectorizer, _, FeatureUnion = _dependencies()
    common = {
        "min_df": config.min_df,
        "max_features": config.max_features,
        "sublinear_tf": True,
    }
    if config.mode == "word":
        return TfidfVectorizer(analyzer="word", ngram_range=(1, 2), max_df=0.98, **common)
    if config.mode == "char":
        return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), **common)
    if config.mode == "word_char":
        return FeatureUnion(
            [
                (
                    "word",
                    TfidfVectorizer(
                        analyzer="word", ngram_range=(1, 2), max_df=0.98, **common
                    ),
                ),
                (
                    "char",
                    TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), **common),
                ),
            ]
        )
    raise BaselineError("an unsupported TF-IDF experiment mode was requested")


def fit_model(samples: Sequence[EmotionSample], config: BaselineConfig) -> FittedBaseline:
    """Fit vectorizer and classifier using only the provided train samples."""

    if len(samples) < 2:
        raise BaselineError("at least two training samples are required")
    labels = [sample.label for sample in samples]
    if len(set(labels)) < 2:
        raise BaselineError("at least two training classes are required")
    texts = [sample.text for sample in samples]
    if any(not text.strip() for text in texts):
        raise BaselineError("training text must not be empty")
    _, LogisticRegression, _ = _dependencies()
    vectorizer = create_vectorizer(config)
    try:
        features = vectorizer.fit_transform(texts)
        model = LogisticRegression(
            class_weight="balanced",
            max_iter=config.max_iter,
            random_state=config.random_state,
        )
        model.fit(features, labels)
    except ValueError as exc:
        raise BaselineError("the selected TF-IDF configuration cannot fit this training split") from exc
    return FittedBaseline(config=config, vectorizer=vectorizer, model=model)


def evaluate_model(fitted: FittedBaseline, samples: Sequence[EmotionSample]) -> dict[str, object]:
    """Evaluate aggregate metrics only; never emit per-record predictions."""

    if not samples:
        raise BaselineError("evaluation split must not be empty")
    try:
        metrics = importlib.import_module("sklearn.metrics")
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise BaselineError("scikit-learn is required for baseline evaluation") from exc
    accuracy_score = metrics.accuracy_score
    confusion_matrix = metrics.confusion_matrix
    precision_recall_fscore_support = metrics.precision_recall_fscore_support
    texts = [sample.text for sample in samples]
    expected = [sample.label for sample in samples]
    predicted = list(fitted.model.predict(fitted.vectorizer.transform(texts)))
    labels = sorted(set(expected) | set(predicted) | set(fitted.model.classes_))
    precision, recall, f1, support = precision_recall_fscore_support(
        expected,
        predicted,
        labels=labels,
        zero_division=0,
    )
    macro_f1 = precision_recall_fscore_support(
        expected, predicted, average="macro", zero_division=0
    )[2]
    weighted_f1 = precision_recall_fscore_support(
        expected, predicted, average="weighted", zero_division=0
    )[2]
    return {
        "sample_count": len(samples),
        "accuracy": round(float(accuracy_score(expected, predicted)), 6),
        "macro_f1": round(float(macro_f1), 6),
        "weighted_f1": round(float(weighted_f1), 6),
        "per_class": {
            label: {
                "precision": round(float(precision[index]), 6),
                "recall": round(float(recall[index]), 6),
                "f1": round(float(f1[index]), 6),
                "support": int(support[index]),
            }
            for index, label in enumerate(labels)
        },
        "confusion_matrix": {
            "labels": labels,
            "matrix": confusion_matrix(expected, predicted, labels=labels).tolist(),
        },
        "predicted_class_distribution": dict(sorted(Counter(predicted).items())),
    }
