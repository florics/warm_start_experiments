"""Solver-independent coupling violation and ordering helpers."""
from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class Coupling:
    row_name: str
    original_name: str
    first_name: str
    second_name: str
    first_index: int
    second_index: int


def disagreement(coupling: Coupling, values: list[float], tolerance: float) -> dict[str, object]:
    first = float(values[coupling.first_index])
    second = float(values[coupling.second_index])
    absolute = abs(first - second)
    satisfied = absolute <= tolerance
    relative = None if satisfied else absolute / max(first, second)
    return {"coupling": coupling, "first_value": first, "second_value": second, "absolute": absolute, "relative": relative, "satisfied": satisfied}


def rank_violations(violations: list[dict[str, object]], strategy: str, rng: random.Random) -> dict[str, object]:
    if not violations:
        raise ValueError("No violated coupling is available")
    if strategy == "relative_ascending":
        return min(violations, key=lambda item: (float(item["relative"]), item["coupling"].row_name))
    if strategy == "relative_descending":
        return max(violations, key=lambda item: (float(item["relative"]), item["coupling"].row_name))
    if strategy == "random":
        return rng.choice(violations)
    raise ValueError(f"Unknown strategy: {strategy}")


def violation_summary(violations: list[dict[str, object]]) -> dict[str, float | int]:
    relatives = [float(item["relative"]) for item in violations]
    return {"count": len(relatives), "max_relative": max(relatives) if relatives else 0.0, "mean_relative": sum(relatives) / len(relatives) if relatives else 0.0}
