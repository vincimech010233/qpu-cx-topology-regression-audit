"""Strict input parsing and deterministic native-CX topology analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class InputError(ValueError):
    """Raised when a JSON input does not match the documented schema."""


def _read_json(path: Path) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise InputError(f"duplicate JSON object key in {path}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise InputError(f"non-standard JSON constant in {path}: {value}")

    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except FileNotFoundError as exc:
        raise InputError(f"input file not found: {path}") from exc
    except (OSError, UnicodeError) as exc:
        raise InputError(f"cannot read input file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"malformed JSON in {path} at line {exc.lineno}, column {exc.colno}") from exc


def _object(value: Any, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{label} must be a JSON object")
    missing = required - value.keys()
    extra = value.keys() - required
    if missing:
        raise InputError(f"{label} is missing field(s): {', '.join(sorted(missing))}")
    if extra:
        raise InputError(f"{label} has unknown field(s): {', '.join(sorted(extra))}")
    return value


def _edge(value: Any, num_qubits: int, label: str) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise InputError(f"{label} must be a two-item array [control, target]")
    control, target = value
    if type(control) is not int or type(target) is not int:
        raise InputError(f"{label} qubit identifiers must be integers")
    if control < 0 or target < 0 or control >= num_qubits or target >= num_qubits:
        raise InputError(f"{label} qubit identifiers must be in [0, {num_qubits - 1}]")
    if control == target:
        raise InputError(f"{label} must connect two different qubits")
    return control, target


def _valid_label(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label} must be a non-empty string")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise InputError(f"{label} must not contain unpaired Unicode surrogates")
    return value


def parse_snapshot(value: Any, label: str = "snapshot") -> dict[str, Any]:
    obj = _object(value, {"name", "num_qubits", "native_cx"}, label)
    name = _valid_label(obj["name"], f"{label}.name")
    count = obj["num_qubits"]
    if type(count) is not int or count < 1:
        raise InputError(f"{label}.num_qubits must be a positive integer")
    raw_edges = obj["native_cx"]
    if not isinstance(raw_edges, list):
        raise InputError(f"{label}.native_cx must be an array")
    edges: set[tuple[int, int]] = set()
    for index, raw in enumerate(raw_edges):
        edge = _edge(raw, count, f"{label}.native_cx[{index}]")
        if edge in edges:
            raise InputError(f"{label}.native_cx contains duplicate directed connection {list(edge)}")
        edges.add(edge)
    return {"name": name, "num_qubits": count, "native_cx": edges}


def parse_workloads(value: Any, num_qubits: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise InputError("workloads must be a JSON array")
    workloads: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(value):
        label = f"workloads[{index}]"
        obj = _object(raw, {"id", "operations"}, label)
        workload_id = _valid_label(obj["id"], f"{label}.id")
        if workload_id in seen_ids:
            raise InputError(f"duplicate workload id: {workload_id}")
        seen_ids.add(workload_id)
        raw_ops = obj["operations"]
        if not isinstance(raw_ops, list):
            raise InputError(f"{label}.operations must be an array")
        operations = [_edge(op, num_qubits, f"{label}.operations[{i}]") for i, op in enumerate(raw_ops)]
        workloads.append({"id": workload_id, "operations": operations})
    return sorted(workloads, key=lambda item: item["id"])


def analyze(before_value: Any, after_value: Any, workload_value: Any) -> dict[str, Any]:
    before = parse_snapshot(before_value, "before")
    after = parse_snapshot(after_value, "after")
    if before["num_qubits"] != after["num_qubits"]:
        raise InputError("before and after snapshots must have the same num_qubits")
    workloads = parse_workloads(workload_value, before["num_qubits"])
    old_edges: set[tuple[int, int]] = before["native_cx"]
    new_edges: set[tuple[int, int]] = after["native_cx"]
    added, removed = sorted(new_edges - old_edges), sorted(old_edges - new_edges)
    workload_results = []
    total_before = total_after = 0
    for workload in workloads:
        ops = workload["operations"]
        missing_before = sorted(set(ops) - old_edges)
        missing_after = sorted(set(ops) - new_edges)
        became_unavailable = sorted(set(missing_after) - set(missing_before))
        became_available = sorted(set(missing_before) - set(missing_after))
        count_before = sum(op not in old_edges for op in ops)
        count_after = sum(op not in new_edges for op in ops)
        total_before += count_before
        total_after += count_after
        if became_unavailable:
            classification = "REGRESSION"
        elif became_available:
            classification = "IMPROVEMENT"
        else:
            classification = "UNCHANGED"
        workload_results.append({
            "id": workload["id"],
            "operation_count": len(ops),
            "missing_native_cx_before": [list(edge) for edge in missing_before],
            "missing_native_cx_after": [list(edge) for edge in missing_after],
            "became_unavailable_after": [list(edge) for edge in became_unavailable],
            "became_available_after": [list(edge) for edge in became_available],
            "unavailable_operation_occurrences_before": count_before,
            "unavailable_operation_occurrences_after": count_after,
            "classification": classification,
        })
    workload_classes = {item["classification"] for item in workload_results}
    if "REGRESSION" in workload_classes:
        overall = "REGRESSION"
    elif "IMPROVEMENT" in workload_classes:
        overall = "IMPROVEMENT"
    elif not added and not removed:
        overall = "UNCHANGED"
    else:
        overall = "NO_WORKLOAD_IMPACT"
    return {
        "schema_version": 1,
        "before": {"name": before["name"], "num_qubits": before["num_qubits"]},
        "after": {"name": after["name"], "num_qubits": after["num_qubits"]},
        "native_cx_changes": {"added": [list(edge) for edge in added], "removed": [list(edge) for edge in removed]},
        "workload_summary": {
            "classification": overall,
            "workload_count": len(workload_results),
            "unavailable_operation_occurrences_before": total_before,
            "unavailable_operation_occurrences_after": total_after,
        },
        "workloads": workload_results,
        "interpretation": (
            "A missing directed pair means the requested CX is not listed as native for that ordered physical-qubit pair "
            "in this snapshot. It does not imply that a circuit cannot be executed: a compiler may use routing, "
            "direction reversal, or decomposition when the target instruction set permits it."
        ),
    }


def analyze_files(before_path: Path, after_path: Path, workloads_path: Path) -> dict[str, Any]:
    before = _read_json(before_path)
    after = _read_json(after_path)
    workloads = _read_json(workloads_path)
    return analyze(before, after, workloads)
