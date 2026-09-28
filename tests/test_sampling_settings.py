"""GPU-free validation and persistence checks for stage token budgets."""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from pydantic import ValidationError

from studio.app import Submission
from studio.config import Config, PIPELINE_DEFAULTS
from studio.queue import Queue
from studio.storage import song_request
from worker import SamplingLimitError, classify, sampling_overrides, validate_sampling_limit


def payload(**values):
    return {"submission_key": "a" * 32, "style": "ambient", "lyrics": "[Verse]", **values}


class SamplingSettingsTests(unittest.TestCase):
    def test_api_accepts_empty_and_each_independent_override(self):
        cases = (
            ({}, None, None),
            ({"abc_max_tokens": 2048}, 2048, None),
            ({"semantic_max_tokens": 6000}, None, 6000),
            ({"abc_max_tokens": 2000, "semantic_max_tokens": 7000}, 2000, 7000),
        )
        for extra, abc, semantic in cases:
            with self.subTest(extra=extra):
                model = Submission.model_validate(payload(**extra))
                self.assertEqual(model.abc_max_tokens, abc)
                self.assertEqual(model.semantic_max_tokens, semantic)

    def test_api_rejects_zero_negative_fraction_and_string(self):
        for value in (0, -1, 1.5, "12", True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Submission.model_validate(payload(abc_max_tokens=value))

    def test_worker_passes_only_explicit_stage_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe = SimpleNamespace(
                generation_config=SimpleNamespace(
                    context=24576,
                    abc=SimpleNamespace(min_tokens=32),
                    semantic=SimpleNamespace(min_tokens=200),
                ),
                model_dir=Path(tmp),
            )
            cases = (
                ({}, {}),
                ({"abc_max_tokens": 1200}, {"abc_sampling": {"max_tokens": 1200}}),
                ({"semantic_max_tokens": 3000}, {"semantic_sampling": {"max_tokens": 3000}}),
                ({"abc_max_tokens": 1200, "semantic_max_tokens": 3000},
                 {"abc_sampling": {"max_tokens": 1200}, "semantic_sampling": {"max_tokens": 3000}}),
            )
            for values, expected in cases:
                with self.subTest(values=values):
                    message = {"request": {"cot": "off", **values}}
                    self.assertEqual(sampling_overrides(message, pipe), expected)
            for values in ({"abc_max_tokens": 31}, {"semantic_max_tokens": 199}):
                with self.subTest(below_min=values), self.assertRaises(SamplingLimitError):
                    sampling_overrides({"request": {"cot": "off", **values}}, pipe)
            with self.assertRaises(SamplingLimitError):
                sampling_overrides({"request": {"cot": "off", "semantic_max_tokens": "1000"}}, pipe)

    def test_worker_uses_actual_minimum_and_prefix_context(self):
        with self.assertRaises(SamplingLimitError) as below_min:
            validate_sampling_limit(199, "semantic", 200)
        self.assertIn("min_tokens=200", str(below_min.exception))
        with self.assertRaises(SamplingLimitError) as overflow:
            validate_sampling_limit(1000, "semantic", 200, prefix_tokens=23577, context=24576)
        self.assertIn("prefix_tokens=23577", str(overflow.exception))
        self.assertEqual(classify(ValueError("Prefix + requested generation budget exceeds 24576; no implicit truncation"))[0],
                         "sampling_limit")
        validate_sampling_limit(999, "semantic", 200, prefix_tokens=23577, context=24576)

    def test_settings_round_trip_through_job_store_without_cross_defaulting(self):
        with tempfile.TemporaryDirectory(prefix="token-settings-") as tmp:
            config = Config("/python", "model", "vae", "cpu", dict(PIPELINE_DEFAULTS), Path(tmp), engine="test")
            queue = Queue(config)
            queue.start()
            try:
                self.assertTrue(queue.ready.wait(5))
                cases = (
                    ({}, {}),
                    ({"abc_max_tokens": 1024}, {"abc_max_tokens": 1024}),
                    ({"semantic_max_tokens": 2048}, {"semantic_max_tokens": 2048}),
                    ({"abc_max_tokens": 1024, "semantic_max_tokens": 2048},
                     {"abc_max_tokens": 1024, "semantic_max_tokens": 2048}),
                )
                for index, (values, expected) in enumerate(cases):
                    spec = {"title": str(index), "style": "test", "lyrics": "words", "cot": "full",
                            "cfg_scale": None, "source_id": None, "abc": None, **values}
                    jobs, _ = queue.store.submit(str(index) * 16, str(index), spec, config.runtime(), [index])
                    job = jobs[0]
                    request = song_request(job)
                    self.assertEqual({k: request[k] for k in expected}, expected)
                    for key in {"abc_max_tokens", "semantic_max_tokens"} - set(expected):
                        self.assertNotIn(key, request)
            finally:
                queue.close()


if __name__ == "__main__":
    unittest.main()
