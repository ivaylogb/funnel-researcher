"""Tests for funnel + dropoff loaders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from funnel_researcher.loaders import load_dropoff, load_funnel


FUNNEL_YAML = """
name: test_funnel
metric: activations
target_dropoff_step: step_b
steps:
  - id: step_a
    name: First step
    success_criterion: did the thing
    typical_duration: under 5 minutes
  - id: step_b
    name: Second step
    success_criterion: did the harder thing
"""


DROPOFF_JSON = {
    "cohort_name": "test_cohort",
    "cohort_size": 100,
    "measurement_window_days": 14,
    "step_counts": {"step_a": 100, "step_b": 40},
    "step_pass_rates": {"step_a_to_step_b": 0.4},
    "target_step_failure_signals": [
        {
            "signal": "400 error on first request",
            "fraction_of_dropoffs": 0.5,
            "step": "step_b",
            "median_developer_calls_before_quit": 2,
        }
    ],
    "qualitative_signals": ["Support tickets mention parameter X."],
}


def test_load_funnel_parses_fields(tmp_path: Path) -> None:
    funnel_file = tmp_path / "funnel.yaml"
    funnel_file.write_text(FUNNEL_YAML)
    funnel = load_funnel(funnel_file)

    assert funnel.name == "test_funnel"
    assert funnel.metric == "activations"
    assert funnel.target_dropoff_step == "step_b"
    assert len(funnel.steps) == 2
    assert funnel.steps[0].id == "step_a"
    assert funnel.steps[1].success_criterion == "did the harder thing"


def test_load_funnel_step_by_id(tmp_path: Path) -> None:
    funnel_file = tmp_path / "funnel.yaml"
    funnel_file.write_text(FUNNEL_YAML)
    funnel = load_funnel(funnel_file)

    assert funnel.step_by_id("step_a").name == "First step"
    assert funnel.step_by_id("missing") is None
    assert funnel.target_step().id == "step_b"


def test_load_funnel_handles_missing_optional_typical_duration(tmp_path: Path) -> None:
    funnel_file = tmp_path / "funnel.yaml"
    funnel_file.write_text(FUNNEL_YAML)
    funnel = load_funnel(funnel_file)

    # step_a has it, step_b doesn't
    assert funnel.steps[0].typical_duration == "under 5 minutes"
    assert funnel.steps[1].typical_duration == ""


def test_load_dropoff_parses_fields(tmp_path: Path) -> None:
    dropoff_file = tmp_path / "dropoff.json"
    dropoff_file.write_text(json.dumps(DROPOFF_JSON))
    dropoff = load_dropoff(dropoff_file)

    assert dropoff.cohort_name == "test_cohort"
    assert dropoff.cohort_size == 100
    assert dropoff.step_counts["step_b"] == 40
    assert len(dropoff.target_step_failure_signals) == 1
    assert dropoff.target_step_failure_signals[0].fraction_of_dropoffs == 0.5
    assert dropoff.qualitative_signals == ["Support tickets mention parameter X."]


def test_load_dropoff_handles_missing_qualitative_signals(tmp_path: Path) -> None:
    payload = {**DROPOFF_JSON}
    del payload["qualitative_signals"]
    dropoff_file = tmp_path / "dropoff.json"
    dropoff_file.write_text(json.dumps(payload))
    dropoff = load_dropoff(dropoff_file)

    assert dropoff.qualitative_signals == []


def test_load_dropoff_handles_missing_median_calls(tmp_path: Path) -> None:
    payload = {**DROPOFF_JSON}
    payload["target_step_failure_signals"] = [
        {
            "signal": "no median field",
            "fraction_of_dropoffs": 0.3,
            "step": "step_b",
        }
    ]
    dropoff_file = tmp_path / "dropoff.json"
    dropoff_file.write_text(json.dumps(payload))
    dropoff = load_dropoff(dropoff_file)

    assert dropoff.target_step_failure_signals[0].median_developer_calls_before_quit is None


def test_load_funnel_raises_on_missing_required_field(tmp_path: Path) -> None:
    bad_yaml = "name: test\n"  # missing metric, target_dropoff_step, steps
    funnel_file = tmp_path / "funnel.yaml"
    funnel_file.write_text(bad_yaml)

    with pytest.raises(KeyError):
        load_funnel(funnel_file)
