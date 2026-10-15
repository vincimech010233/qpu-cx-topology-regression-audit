# Native directed CX topology audit

- Before: **synthetic-before** (4 qubits)
- After: **synthetic-after** (4 qubits)
- Overall workload classification: **REGRESSION**

## Connectivity changes

### Added native directed CX connections

- `2 → 1`

### Removed native directed CX connections

- `1 → 2`

## Workload impact

| Workload | Classification | Unavailable before | Unavailable after |
|---|---:|---:|---:|
| `fixed-mapping-a` | REGRESSION | 0 | 1 |
| `fixed-mapping-b` | UNCHANGED | 1 | 1 |

## Interpretation

A missing directed pair means the requested CX is not listed as native for that ordered physical-qubit pair in this snapshot. It does not imply that a circuit cannot be executed: a compiler may use routing, direction reversal, or decomposition when the target instruction set permits it.

The analysis checks the explicitly listed ordered physical-qubit pairs only. It does not compile, route, or estimate the cost or success probability of a circuit.
