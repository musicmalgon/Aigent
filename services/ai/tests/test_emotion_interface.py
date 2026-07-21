"""Interface tests using only synthetic in-memory model doubles."""

from __future__ import annotations

import tempfile
import unittest
from inspect import Parameter, signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_type_hints
from unittest.mock import patch

from ai.src.emotion import (
    EmotionAnalyzer,
    EmotionAnalyzerError,
    EmptyDiaryTextError,
    ModelArtifactNotConfiguredError,
    ModelArtifactNotFoundError,
    ModelLoadError,
    ModelNotLoadedError,
    ModelNotReadyError,
    ModelNotTrainedError,
    OptionalDependencyError,
    OptionalDependencyMissingError,
    PredictionError,
    PredictionExecutionError,
    PredictionOutputError,
    TfidfEmotionAnalyzer,
    TransformerEmotionAnalyzer,
)
from ai.src.schemas import EmotionAnalysis, EmotionLabel


SYNTHETIC_TFIDF_NAME = "synthetic-tfidf"
SYNTHETIC_TRANSFORMER_NAME = "synthetic-transformer"
SYNTHETIC_MODEL_VERSION = "synthetic-test-v1"


def _tfidf_analyzer(
    model_path: str | Path | None = None,
    vectorizer_path: str | Path | None = None,
) -> TfidfEmotionAnalyzer:
    return TfidfEmotionAnalyzer(
        model_path,
        vectorizer_path,
        model_name=SYNTHETIC_TFIDF_NAME,
        model_version=SYNTHETIC_MODEL_VERSION,
    )


def _transformer_analyzer(
    model_path: str | Path | None = None,
) -> TransformerEmotionAnalyzer:
    return TransformerEmotionAnalyzer(
        model_path,
        model_name=SYNTHETIC_TRANSFORMER_NAME,
        model_version=SYNTHETIC_MODEL_VERSION,
    )


class _SyntheticVectorizer:
    def transform(self, texts: list[str]) -> list[str]:
        return texts


class _SyntheticClassifier:
    classes_ = ["stable", "fatigue", "anxiety", "other"]

    def predict(self, features: list[str]) -> list[str]:
        del features
        return ["fatigue"]

    def predict_proba(self, features: list[str]) -> list[list[float]]:
        del features
        return [[0.05, 0.80, 0.10, 0.05]]


class _SyntheticUntrainedClassifier:
    pass


class _SyntheticFailingVectorizer:
    def transform(self, texts: list[str]) -> list[str]:
        del texts
        raise RuntimeError("synthetic vectorizer failure")


class _SyntheticEmptyPredictionClassifier(_SyntheticClassifier):
    def predict(self, features: list[str]) -> list[str]:
        del features
        return []


class _SyntheticAutoLoader:
    calls: list[tuple[Path, bool]] = []

    @classmethod
    def from_pretrained(
        cls,
        model_path: Path,
        *,
        local_files_only: bool,
    ) -> object:
        cls.calls.append((model_path, local_files_only))
        return object()


class _SyntheticFailingAutoLoader:
    @classmethod
    def from_pretrained(
        cls,
        model_path: Path,
        *,
        local_files_only: bool,
    ) -> object:
        del cls, model_path, local_files_only
        raise RuntimeError("synthetic local backend load failure")


class EmotionInterfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        _SyntheticAutoLoader.calls.clear()

    def test_both_analyzers_share_the_abstract_interface(self) -> None:
        self.assertTrue(issubclass(TfidfEmotionAnalyzer, EmotionAnalyzer))
        self.assertTrue(issubclass(TransformerEmotionAnalyzer, EmotionAnalyzer))
        self.assertIs(
            get_type_hints(TfidfEmotionAnalyzer.predict)["return"],
            EmotionAnalysis,
        )
        self.assertIs(
            get_type_hints(TransformerEmotionAnalyzer.predict)["return"],
            EmotionAnalysis,
        )
        for analyzer_class in (TfidfEmotionAnalyzer, TransformerEmotionAnalyzer):
            parameters = signature(analyzer_class).parameters
            self.assertIs(parameters["model_name"].default, Parameter.empty)
            self.assertIs(parameters["model_version"].default, Parameter.empty)

    def test_public_failures_share_the_common_error_hierarchy(self) -> None:
        for error_type in (
            ModelArtifactNotConfiguredError,
            ModelArtifactNotFoundError,
            ModelLoadError,
            ModelNotLoadedError,
            ModelNotTrainedError,
            OptionalDependencyMissingError,
        ):
            with self.subTest(error_type=error_type.__name__):
                self.assertTrue(issubclass(error_type, ModelNotReadyError))
                self.assertTrue(issubclass(error_type, EmotionAnalyzerError))
        self.assertTrue(
            issubclass(OptionalDependencyMissingError, OptionalDependencyError)
        )

        for error_type in (PredictionExecutionError, PredictionOutputError):
            with self.subTest(error_type=error_type.__name__):
                self.assertTrue(issubclass(error_type, PredictionError))
                self.assertTrue(issubclass(error_type, EmotionAnalyzerError))

    def test_model_metadata_must_be_non_empty(self) -> None:
        with self.assertRaisesRegex(ValueError, "model_name"):
            TfidfEmotionAnalyzer(
                model_name=" ",
                model_version=SYNTHETIC_MODEL_VERSION,
            )
        with self.assertRaisesRegex(ValueError, "model_version"):
            TransformerEmotionAnalyzer(
                model_name=SYNTHETIC_TRANSFORMER_NAME,
                model_version=" ",
            )

    def test_empty_text_has_a_clear_error_before_model_access(self) -> None:
        analyzers: list[EmotionAnalyzer] = [
            _tfidf_analyzer(),
            _transformer_analyzer(),
        ]
        for analyzer in analyzers:
            with self.subTest(analyzer=type(analyzer).__name__):
                with self.assertRaisesRegex(
                    EmptyDiaryTextError,
                    "empty or whitespace-only",
                ):
                    analyzer.predict("   ")

    def test_tfidf_distinguishes_unconfigured_missing_and_unloaded(self) -> None:
        with self.assertRaisesRegex(
            ModelArtifactNotConfiguredError,
            "must both be configured",
        ):
            _tfidf_analyzer().predict("합성 일기 문장")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            missing_model = root / "missing-model.joblib"
            missing_vectorizer = root / "missing-vectorizer.joblib"
            with self.assertRaisesRegex(
                ModelArtifactNotFoundError,
                "artifact file",
            ):
                _tfidf_analyzer(
                    missing_model,
                    missing_vectorizer,
                ).predict("합성 일기 문장")

            model_path = root / "model.joblib"
            vectorizer_path = root / "vectorizer.joblib"
            model_path.touch()
            vectorizer_path.touch()
            with self.assertRaisesRegex(ModelNotLoadedError, "call load"):
                _tfidf_analyzer(
                    model_path,
                    vectorizer_path,
                ).predict("합성 일기 문장")

    def test_tfidf_missing_dependency_is_lazily_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            model_path = root / "model.joblib"
            vectorizer_path = root / "vectorizer.joblib"
            model_path.touch()
            vectorizer_path.touch()
            analyzer = _tfidf_analyzer(model_path, vectorizer_path)

            missing_joblib = ModuleNotFoundError(
                "No module named 'joblib'",
                name="joblib",
            )
            with patch(
                "ai.src.emotion.tfidf_analyzer.importlib.import_module",
                side_effect=missing_joblib,
            ):
                with self.assertRaisesRegex(
                    OptionalDependencyError,
                    "compatible 'joblib'",
                ) as raised:
                    analyzer.load()
                self.assertIsInstance(
                    raised.exception,
                    OptionalDependencyMissingError,
                )

    def test_tfidf_load_failure_preserves_its_cause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            model_path = root / "model.joblib"
            vectorizer_path = root / "vectorizer.joblib"
            model_path.touch()
            vectorizer_path.touch()
            analyzer = _tfidf_analyzer(model_path, vectorizer_path)

            def fail_load(path: Path) -> object:
                del path
                raise ValueError("synthetic corrupt artifact")

            with patch(
                "ai.src.emotion.tfidf_analyzer.importlib.import_module",
                return_value=SimpleNamespace(load=fail_load),
            ):
                with self.assertRaises(ModelLoadError) as raised:
                    analyzer.load()

            self.assertIsInstance(raised.exception.__cause__, ValueError)

    def test_tfidf_adapts_loaded_artifacts_to_common_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            model_path = root / "model.joblib"
            vectorizer_path = root / "vectorizer.joblib"
            model_path.touch()
            vectorizer_path.touch()
            analyzer = TfidfEmotionAnalyzer(
                model_path,
                vectorizer_path,
                model_name=SYNTHETIC_TFIDF_NAME,
                model_version=SYNTHETIC_MODEL_VERSION,
            )
            fake_joblib = SimpleNamespace(
                load=lambda path: (
                    _SyntheticClassifier()
                    if path == model_path
                    else _SyntheticVectorizer()
                )
            )

            with patch(
                "ai.src.emotion.tfidf_analyzer.importlib.import_module",
                return_value=fake_joblib,
            ):
                analyzer.load()

            result = analyzer.predict("합성 피로 일기 문장")
            self.assertIsInstance(result, EmotionAnalysis)
            self.assertIs(result.primary_emotion, EmotionLabel.FATIGUE)
            self.assertEqual(result.confidence, 0.80)
            self.assertEqual(result.secondary_signals, [])
            self.assertIsNone(result.sleep_related)
            self.assertIsNone(result.workload_related)

    def test_tfidf_reports_an_untrained_loaded_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            model_path = root / "model.joblib"
            vectorizer_path = root / "vectorizer.joblib"
            model_path.touch()
            vectorizer_path.touch()
            analyzer = _tfidf_analyzer(model_path, vectorizer_path)
            fake_joblib = SimpleNamespace(
                load=lambda path: (
                    _SyntheticUntrainedClassifier()
                    if path == model_path
                    else _SyntheticVectorizer()
                )
            )

            with patch(
                "ai.src.emotion.tfidf_analyzer.importlib.import_module",
                return_value=fake_joblib,
            ):
                analyzer.load()

            with self.assertRaisesRegex(ModelNotTrainedError, "fitted"):
                analyzer.predict("합성 일기 문장")

    def test_tfidf_prediction_errors_are_typed_and_chained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            model_path = root / "model.joblib"
            vectorizer_path = root / "vectorizer.joblib"
            model_path.touch()
            vectorizer_path.touch()

            cases = [
                (
                    _SyntheticClassifier(),
                    _SyntheticFailingVectorizer(),
                    PredictionExecutionError,
                ),
                (
                    _SyntheticEmptyPredictionClassifier(),
                    _SyntheticVectorizer(),
                    PredictionOutputError,
                ),
            ]
            for model, vectorizer, expected_error in cases:
                with self.subTest(expected_error=expected_error.__name__):
                    analyzer = _tfidf_analyzer(model_path, vectorizer_path)
                    fake_joblib = SimpleNamespace(
                        load=lambda path: (model if path == model_path else vectorizer)
                    )
                    with patch(
                        "ai.src.emotion.tfidf_analyzer.importlib.import_module",
                        return_value=fake_joblib,
                    ):
                        analyzer.load()

                    with self.assertRaises(expected_error) as raised:
                        analyzer.predict("합성 일기 문장")
                    self.assertIsNotNone(raised.exception.__cause__)

    def test_transformer_unconfigured_and_optional_dependency_errors(self) -> None:
        with self.assertRaisesRegex(
            ModelArtifactNotConfiguredError,
            "local",
        ):
            _transformer_analyzer().predict("합성 일기 문장")

        with tempfile.TemporaryDirectory() as temporary_directory:
            analyzer = _transformer_analyzer(temporary_directory)
            missing_transformers = ModuleNotFoundError(
                "No module named 'transformers'",
                name="transformers",
            )
            with patch(
                "ai.src.emotion.transformer_analyzer.importlib.import_module",
                side_effect=missing_transformers,
            ):
                with self.assertRaisesRegex(
                    OptionalDependencyError,
                    "optional 'transformers'",
                ) as raised:
                    analyzer.load()
                self.assertIsInstance(
                    raised.exception,
                    OptionalDependencyMissingError,
                )

    def test_transformer_distinguishes_missing_and_unloaded_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(
                ModelArtifactNotFoundError,
                "directory not found",
            ):
                _transformer_analyzer(root / "missing").predict("합성 일기 문장")

            with self.assertRaisesRegex(ModelNotLoadedError, "call load"):
                _transformer_analyzer(root).predict("합성 일기 문장")

    def test_transformer_uses_local_only_loading_and_common_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory)

            def synthetic_pipeline(
                task: str,
                *,
                model: object,
                tokenizer: object,
            ) -> Any:
                self.assertEqual(task, "text-classification")
                self.assertIsNotNone(model)
                self.assertIsNotNone(tokenizer)
                return lambda text: [{"label": "anxiety", "score": 0.70}]

            fake_transformers = SimpleNamespace(
                AutoTokenizer=_SyntheticAutoLoader,
                AutoModelForSequenceClassification=_SyntheticAutoLoader,
                pipeline=synthetic_pipeline,
            )
            analyzer = TransformerEmotionAnalyzer(
                model_path,
                model_name=SYNTHETIC_TRANSFORMER_NAME,
                model_version=SYNTHETIC_MODEL_VERSION,
            )
            with patch(
                "ai.src.emotion.transformer_analyzer.importlib.import_module",
                return_value=fake_transformers,
            ):
                analyzer.load()

            self.assertEqual(
                _SyntheticAutoLoader.calls,
                [(model_path, True), (model_path, True)],
            )
            result = analyzer.predict("합성 불안 일기 문장")
            self.assertIsInstance(result, EmotionAnalysis)
            self.assertIs(result.primary_emotion, EmotionLabel.ANXIETY)
            self.assertEqual(result.confidence, 0.70)
            self.assertIsNone(result.sleep_related)
            self.assertIsNone(result.workload_related)

    def test_transformer_load_failure_is_typed_and_chained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory)
            fake_transformers = SimpleNamespace(
                AutoTokenizer=_SyntheticFailingAutoLoader,
                AutoModelForSequenceClassification=_SyntheticAutoLoader,
                pipeline=lambda *args, **kwargs: None,
            )
            analyzer = _transformer_analyzer(model_path)

            with patch(
                "ai.src.emotion.transformer_analyzer.importlib.import_module",
                return_value=fake_transformers,
            ):
                with self.assertRaisesRegex(
                    ModelLoadError,
                    "local directory",
                ) as raised:
                    analyzer.load()

            self.assertIsInstance(raised.exception.__cause__, RuntimeError)

    def test_transformer_rejects_unsupported_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            analyzer = _transformer_analyzer(temporary_directory)
            invalid_outputs: list[object] = [
                [],
                [{}],
                [{"label": "stable", "score": 1.5}],
                [{"label": "unsupported", "score": 0.5}],
            ]

            for output in invalid_outputs:
                with self.subTest(output=output):
                    analyzer._classifier = lambda text, value=output: value
                    with self.assertRaises(PredictionOutputError):
                        analyzer.predict("합성 일기 문장")

    def test_transformer_prediction_failure_is_typed_and_chained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory)

            def synthetic_pipeline(
                task: str,
                *,
                model: object,
                tokenizer: object,
            ) -> Any:
                del task, model, tokenizer

                def fail_prediction(text: str) -> list[dict[str, object]]:
                    del text
                    raise RuntimeError("synthetic backend failure")

                return fail_prediction

            fake_transformers = SimpleNamespace(
                AutoTokenizer=_SyntheticAutoLoader,
                AutoModelForSequenceClassification=_SyntheticAutoLoader,
                pipeline=synthetic_pipeline,
            )
            analyzer = _transformer_analyzer(model_path)
            with patch(
                "ai.src.emotion.transformer_analyzer.importlib.import_module",
                return_value=fake_transformers,
            ):
                analyzer.load()

            with self.assertRaises(PredictionExecutionError) as raised:
                analyzer.predict("합성 일기 문장")
            self.assertIsInstance(raised.exception.__cause__, RuntimeError)


if __name__ == "__main__":
    unittest.main()
