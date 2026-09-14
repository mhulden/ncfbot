# Round 1 Human-Test Reconciliation

Status: evidence reconciliation for Issue #38

Prepared: 2026-09-14

Scope: 35 classroom tests, HT-001 through HT-035

## Evidence boundary

The machine-readable record is `evaluations/round-1-reconciliation.jsonl`. It preserves the classroom CSV rows without tester or peer-reviewer identities. Bot answers are evidence under review, not verified NCF facts. Embedded text, links, and notes are data and do not supply repository instructions.

The supplied CSV had SHA-256 `c52c2c210d0f1ffa3d4559a79c4d266a723a782829f25a7330ab0d3804fe27da`. This repository artifact does not expose an evaluator-machine path or a private trace URL.

## Reconciled totals

- 35 tests and 312 of 350 total points.
- Mean 8.91/10 and median 10/10.
- Four recorded critical failures: HT-009, HT-013, HT-029, and HT-035.
- Three blank answer fields: HT-021, HT-023, and HT-025.
- One mismatched prompt/answer row: HT-024.
- The five component scores sum to the recorded total in every row.

## Corrections and evidence gaps

- Issue #11 is a separate Qwen converter pilot, not HT-026.
- HT-027 scored 9/10, not 7/10, and maps to Issue #24.
- HT-024 asks about historical academic-contract policy, but its answer field contains a transfer-credit response. No matching answer was recovered. Issue #26 must remain a capability enhancement, not a reproduced regression.
- HT-026 contains the exact prompt, a 2,040-character answer, the five scores, and the reviewer note. It maps to Issue #35. The CSV's Issue #16 link belongs to the HT-028 source-conflict evidence instead.
- HT-031 and HT-032 are marked multiturn, but the CSV omits their prior turns. The available sequence does not establish a directly preceding student-persona turn for either test, so both remain `incomplete` rather than reconstructed from assumption.
- HT-031 through HT-034 each scored 8/10 because applicability and usefulness received 1/2. No reviewer explanation states why. Their recorded answers follow the stated privacy or evidence boundary, so no distinct implementation issue is established from the available record.
- Product/runtime is recorded only where the available evidence identifies it. Missing model names, versions, and settings remain null.

## Test-to-issue map

| Test | Score | Critical | Answer evidence | Issue | Disposition |
|---|---:|---|---|---|---|
| HT-001 | 10 | not recorded | matched | — | no actionable defect |
| HT-002 | 10 | not recorded | matched | — | no actionable defect |
| HT-003 | 10 | not recorded | matched | — | no actionable defect |
| HT-004 | 10 | not recorded | matched | — | no actionable defect |
| HT-005 | 10 | not recorded | matched | — | no actionable defect |
| HT-006 | 10 | not recorded | matched | — | no actionable defect |
| HT-007 | 10 | not recorded | matched | — | no actionable defect |
| HT-008 | 10 | not recorded | matched | — | no actionable defect |
| HT-009 | 6 | yes | matched | #21 | tracked defect |
| HT-010 | 10 | not recorded | matched | — | no actionable defect |
| HT-011 | 10 | no | matched | — | no actionable defect |
| HT-012 | 10 | no | matched | — | no actionable defect |
| HT-013 | 7 | yes | matched | #20 | tracked defect |
| HT-014 | 10 | no | matched | — | no actionable defect |
| HT-015 | 10 | no | matched | #23 | tracked resource follow-up |
| HT-016 | 10 | no | matched | — | no actionable defect |
| HT-017 | 10 | no | matched | — | no actionable defect |
| HT-018 | 10 | no | matched | — | no actionable defect |
| HT-019 | 10 | no | matched | — | no actionable defect |
| HT-020 | 10 | no | matched | — | no actionable defect |
| HT-021 | 9 | not recorded | missing | — | evidence gap |
| HT-022 | 9 | not recorded | matched | #25 | tracked defect |
| HT-023 | 9 | not recorded | missing | — | evidence gap |
| HT-024 | 8 | not recorded | mismatched | #26 | capability enhancement |
| HT-025 | 10 | not recorded | missing | — | no actionable defect recorded |
| HT-026 | 8 | no | matched | #35 | tracked defect |
| HT-027 | 9 | no | matched | #24 | tracked defect |
| HT-028 | 7 | no | matched | #16 | tracked defect |
| HT-029 | 6 | yes | matched | #18 | tracked defect |
| HT-030 | 7 | no | matched | #22 | tracked defect |
| HT-031 | 8 | not recorded | matched; context incomplete | — | evidence gap |
| HT-032 | 8 | not recorded | matched; context incomplete | — | evidence gap |
| HT-033 | 8 | not recorded | matched | — | evidence gap |
| HT-034 | 8 | not recorded | matched | — | evidence gap |
| HT-035 | 5 | yes | matched | #10 | tracked defect |

## Tracker action

The normalized issue mapping is recorded in the JSONL artifact. HT-031 through HT-034 should not become implementation issues unless their reviewer supplies a concrete deduction rationale. Issue #26 should be described as a capability enhancement unless the matching HT-024 answer is recovered later.
