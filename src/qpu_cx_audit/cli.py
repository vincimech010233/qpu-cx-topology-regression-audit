"""Command-line interface."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tempfile
from pathlib import Path

from .core import InputError, analyze_files


def _markdown_cell(value: str) -> str:
    safe = "".join(" " if ord(char) < 32 or 0x7F <= ord(char) <= 0x9F else char for char in value)
    safe = html.escape(safe, quote=True)
    return (safe.replace("\\", "\\\\").replace("|", "\\|")
            .replace("`", "\\`").replace("*", "\\*").replace("_", "\\_")
            .replace("[", "\\[").replace("]", "\\]"))


def render_markdown(report: dict) -> str:
    summary = report["workload_summary"]
    lines = [
        "# Native directed CX topology audit", "",
        f"- Before: **{_markdown_cell(report['before']['name'])}** ({report['before']['num_qubits']} qubits)",
        f"- After: **{_markdown_cell(report['after']['name'])}** ({report['after']['num_qubits']} qubits)",
        f"- Overall workload classification: **{summary['classification']}**", "",
        "## Connectivity changes", "",
        "### Added native directed CX connections", "",
    ]
    lines.extend([f"- `{a} → {b}`" for a, b in report["native_cx_changes"]["added"]] or ["- None"])
    lines.extend(["", "### Removed native directed CX connections", ""])
    lines.extend([f"- `{a} → {b}`" for a, b in report["native_cx_changes"]["removed"]] or ["- None"])
    lines.extend(["", "## Workload impact", "", "| Workload | Classification | Unavailable before | Unavailable after |", "|---|---:|---:|---:|"])
    for workload in report["workloads"]:
        lines.append(
            f"| {_markdown_cell(workload['id'])} | {workload['classification']} | "
            f"{workload['unavailable_operation_occurrences_before']} | "
            f"{workload['unavailable_operation_occurrences_after']} |"
        )
    if not report["workloads"]:
        lines.append("| _No workloads_ | — | 0 | 0 |")
    lines.extend([
        "", "## Interpretation", "", report["interpretation"], "",
        "The analysis checks the explicitly listed ordered physical-qubit pairs only. It does not compile, route, "
        "or estimate the cost or success probability of a circuit.", "",
    ])
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as stream:
            temp_name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except (OSError, UnicodeError) as exc:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        if isinstance(exc, OSError):
            raise
        raise OSError(f"cannot encode report as UTF-8: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two snapshots of native directed CX connectivity.")
    parser.add_argument("before", type=Path, help="before snapshot JSON")
    parser.add_argument("after", type=Path, help="after snapshot JSON")
    parser.add_argument("workloads", type=Path, help="workload JSON")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd(), help="existing directory for report.json and report.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = analyze_files(args.before, args.after, args.workloads)
    except InputError as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    try:
        if not args.output_dir.is_dir():
            raise OSError(f"output directory does not exist or is not a directory: {args.output_dir}")
        output_json = args.output_dir / "report.json"
        output_md = args.output_dir / "report.md"
        input_paths = {p.resolve() for p in (args.before, args.after, args.workloads)}
        if output_json.resolve() in input_paths or output_md.resolve() in input_paths:
            raise OSError("report paths must not overwrite an input file")
        if output_json.resolve() == output_md.resolve():
            raise OSError("report paths resolve to the same file")
        json_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        _atomic_write(output_json, json_text)
        _atomic_write(output_md, render_markdown(report))
    except OSError as exc:
        print(f"output error: {exc}", file=sys.stderr)
        return 3
    print(f"Wrote {output_json} and {output_md}")
    return 0
