"""Loaders for funnel definitions and dropoff data.

Funnels are YAML; dropoff data is JSON. Both are parsed into typed
dataclasses so the rest of the pipeline operates on a stable contract
rather than raw dicts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FunnelStep:
    id: str
    name: str
    success_criterion: str
    typical_duration: str = ""


@dataclass
class FunnelDefinition:
    """Parsed funnel YAML."""

    name: str
    metric: str
    target_dropoff_step: str
    steps: list[FunnelStep]
    raw: dict  # the original parsed YAML, for round-trip into the prompt

    def step_by_id(self, step_id: str) -> FunnelStep | None:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def target_step(self) -> FunnelStep | None:
        return self.step_by_id(self.target_dropoff_step)


@dataclass
class FailureSignal:
    signal: str
    fraction_of_dropoffs: float
    step: str
    median_developer_calls_before_quit: int | None = None


@dataclass
class DropoffData:
    """Parsed dropoff JSON."""

    cohort_name: str
    cohort_size: int
    measurement_window_days: int
    step_counts: dict[str, int]
    step_pass_rates: dict[str, float]
    target_step_failure_signals: list[FailureSignal]
    qualitative_signals: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def load_funnel(path: Path) -> FunnelDefinition:
    """Load a funnel definition from YAML."""
    raw = yaml.safe_load(path.read_text())
    steps = [
        FunnelStep(
            id=s["id"],
            name=s["name"],
            success_criterion=s["success_criterion"],
            typical_duration=s.get("typical_duration", ""),
        )
        for s in raw.get("steps", [])
    ]
    return FunnelDefinition(
        name=raw["name"],
        metric=raw["metric"],
        target_dropoff_step=raw["target_dropoff_step"],
        steps=steps,
        raw=raw,
    )


def load_dropoff(path: Path) -> DropoffData:
    """Load dropoff data from JSON."""
    raw = json.loads(path.read_text())
    signals = [
        FailureSignal(
            signal=s["signal"],
            fraction_of_dropoffs=s["fraction_of_dropoffs"],
            step=s["step"],
            median_developer_calls_before_quit=s.get("median_developer_calls_before_quit"),
        )
        for s in raw.get("target_step_failure_signals", [])
    ]
    return DropoffData(
        cohort_name=raw["cohort_name"],
        cohort_size=raw["cohort_size"],
        measurement_window_days=raw["measurement_window_days"],
        step_counts=raw["step_counts"],
        step_pass_rates=raw["step_pass_rates"],
        target_step_failure_signals=signals,
        qualitative_signals=raw.get("qualitative_signals", []),
        raw=raw,
    )
