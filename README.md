# QPU CX Topology Regression Audit

A small, offline Python command-line tool for comparing two snapshots of **native directed CX connectivity** and reporting how the changes affect workloads that already name physical control/target qubit pairs.

## Business problem and intended users

Quantum hardware, compiler, and validation teams may need a compact review artifact when a backend's published native two-qubit instruction map changes. This tool answers a narrow question: for the exact ordered physical pairs in a supplied workload list, how many requested CX operations are listed as native in each snapshot?

It is aimed at engineers reviewing configuration changes, regression fixtures, or synthetic examples. It does not fetch processor data or identify/validate a real backend.

## Features

- Strict JSON schemas: required fields only, duplicate JSON keys and non-standard JSON constants rejected, types and qubit bounds checked.
- Directed edge comparison. `[0, 1]` (control 0, target 1) differs from `[1, 0]`.
- Added and removed native CX pair lists, sorted deterministically.
- Per-workload and overall `REGRESSION`, `IMPROVEMENT`, `UNCHANGED`, or `NO_WORKLOAD_IMPACT` classification.
- JSON and Markdown reports without timestamps or random values.
- No network access, telemetry, quantum SDK, or runtime dependency.
- Exit code `0` success, `2` input/argument error, `3` report output error.

## Installation and offline use

Requires Python 3.10 or newer. The analysis code uses only the Python standard library. From this directory, run directly without installing a package:

```sh
PYTHONPATH=src python3 -m qpu_cx_audit \
  examples/before.json examples/after.json examples/workloads.json \
  --output-dir ./out
```

`--output-dir` must already exist. The command writes `report.json` and `report.md` there. For an installed console command, install the local project with `python3 -m pip install .`; package installation uses the standard setuptools build backend, but analysis and execution have no third-party runtime dependencies.

## Synthetic example

The included snapshots use four synthetic qubits. The directed connection `1 → 2` is removed and `2 → 1` is added. Workload `fixed-mapping-a` requests `1 → 2`, so that fixed physical request has one more operation without a native CX entry after the change. This flags a native-topology regression for that workload; it does not establish that the circuit cannot be run.

```sh
mkdir -p out
PYTHONPATH=src python3 -m qpu_cx_audit \
  examples/before.json examples/after.json examples/workloads.json --output-dir out
```

Snapshot shape:

```json
{"name": "synthetic-before", "num_qubits": 4, "native_cx": [[0, 1], [1, 0]]}
```

Workload shape:

```json
[{"id": "fixed-pairs", "operations": [[0, 1], [2, 3]]}]
```

Each workload operation is an ordered pair of physical qubits. Duplicate workload operations are allowed and count as repeated operation occurrences. Duplicate snapshot connections are rejected. The before and after snapshots must declare the same positive qubit count, and all identifiers must be in range.

## Classification

For each workload, the tool counts operation occurrences whose exact directed pair is absent from the snapshot. It also compares the sets of unavailable pairs. A pair newly unavailable after the change makes that workload `REGRESSION`, even if another pair became available and the total count stayed equal. If no pair became newly unavailable but a pair became available, the workload is `IMPROVEMENT`; otherwise it is `UNCHANGED`. Overall classification prioritizes any workload regression, then any improvement; if no workload pair changed, changed topology is `NO_WORKLOAD_IMPACT`, while an identical topology is `UNCHANGED`. Thus an improvement in one workload cannot hide a regression in another.

This is a structural check of explicitly listed pairs, not an estimate of compilation cost, execution quality, fidelity, or runtime.

## Architecture

`src/qpu_cx_audit/core.py` validates input and performs set-based directed edge comparison. `cli.py` handles argument parsing, stable report rendering, and atomic replacement of each output file. Inputs are read only. Reports refuse paths that resolve to an input file. No backend adapters or external services are present.

## Existing tools and differentiation

Qiskit already models directed coupling maps and backend `Target` instructions, and its transpiler handles layout, routing (including SWAP insertion), direction reversal, and gate translation. Those are broader compiler capabilities. This project is not a transpiler, scheduler, simulator, or new quantum algorithm; it is a deliberately small offline snapshot diff plus fixed-workload report that does not require Qiskit or backend credentials. See the [Qiskit coupling-map guide](https://qiskit.qotlabs.org/docs/guides/represent-quantum-computers), [Qiskit transpiler overview](https://qiskit.qotlabs.org/docs/api/qiskit/transpiler), and [transpilation guide](https://qiskit.qotlabs.org/docs/guides/transpile).

The public portfolio research found prior quantum-learning notebooks and a quantum chess prototype, but no previous project in the accessible profile list for comparing processor CX snapshots against fixed physical workloads. The existing [OEE and Downtime Analyzer](https://github.com/vincimech010233/oee-downtime-analyzer) analyzes synthetic manufacturing shift CSV data and produces OEE/Pareto metrics; it does not perform or supply a component to this quantum connectivity audit. This project is distinct in business problem and input/output, but its usefulness beyond this narrow audit remains **INFERRED**, not user-validated.

## Limitations

- Checks only native directed CX entries explicitly supplied in the snapshots. It does not infer other gates or hardware behavior.
- Requires equal qubit counts; it does not model qubit remapping, disabled qubits, or device revisions that renumber qubits.
- A missing native directed pair does **not** mean a circuit is impossible to execute. A compiler may route with SWAPs, reverse CX direction using supported one-qubit operations, or decompose through another native gate. Whether those paths exist or what they cost depends on the actual target and compiler and is outside this tool.
- No hardware data are included; examples and tests are synthetic.
- The overall `REGRESSION` label takes precedence if one workload regresses while another improves; per-workload rows and became-available/became-unavailable pair lists preserve both effects.

## Threat model

Inputs are local JSON files and are treated as untrusted. The parser rejects malformed JSON, duplicate object keys, non-standard numeric constants, unknown fields, wrong types, unpaired Unicode surrogates, duplicate connections, self-links, and out-of-range identifiers. Markdown output escapes user-supplied names and IDs to prevent table/format injection. Input files are never written. Output files are written via temporary files and atomic replacement; resolved output paths may not equal input paths. The tool does not execute input content, open network connections, load plugins, or process secrets. It is not a sandbox: run it with ordinary least-privilege filesystem permissions, and review the chosen output directory. The two report files are replaced separately, so an operating-system failure between replacements could leave reports from different runs.

## Tests and reproducibility

Run the deterministic standard-library test suite from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

**Actual test result:** 18 tests passed with Python 3.12.3 in the workspace and in the `python:3.12-slim-bookworm` container. The container ran as UID/GID 65534 with networking disabled, a read-only root filesystem, a read-only project mount, and a temporary `/tmp`. A wheel also built successfully with `pip wheel --no-deps --no-build-isolation`; no package was installed globally.

No external test service is required. A GitHub Actions workflow runs the same suite on pushes and pull requests using Python 3.10–3.13.

## License

MIT. See [LICENSE](LICENSE).
