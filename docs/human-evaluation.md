# Human Evaluation Run Records

The Round 2 format separates final-answer quality from routing, retrieval, timing, and response order. It is provider-neutral and supports fresh and multiturn tests.

## Files

- `evaluations/templates/round-2-human-run.csv`: header-only template for Google Sheets or another CSV editor.
- `schemas/human-evaluation-run.schema.json`: machine-readable JSON record contract.
- `evaluations/examples/round-2-human-run.jsonl`: synthetic completed record used by tests.

## CSV workflow

Create one row per run. Keep every field, even when its value is blank. JSON-valued columns must contain valid JSON when populated:

- `settings_json`: object or blank.
- `prior_context_json`: ordered `[{"role":"user|assistant","content":"..."}]`, `[]` when checked and empty, or blank when not recorded.
- `resources_json`: ordered resource-delivery objects, `[]` when checked and none were used, or blank when not recorded.
- `tool_events_json`: ordered event objects, `[]` when checked and no tools ran, or blank when not recorded.
- `trace_reference`: durable public-safe trace identifier when ordered events are stored elsewhere. Do not put evaluator-machine paths in this field.

This distinction prevents an unrecorded value from being reported as a checked negative. `source_verification` separately uses `checked-yes`, `checked-no`, `not-checked`, or `not-applicable`.

Use ISO 8601 UTC timestamps. Record the full 40-character repository revision and the SHA-256 resource-manifest hash. Preserve the product, model, version, runtime, and material settings exactly as shown by the test environment; do not infer them from another run.
Leave an unavailable product, model, version, runtime, or settings field blank so the normalized JSON records it as null. Do not use `unknown` as if it were a measured value.

## Focused Round 2 starter set

- HT-009 / Issue #21: record whether the required faculty-systems resource was supplied or retrieved before any system claim. Check the answer for unsupported dashboard, menu, button, tile, or click-path language.
- HT-013 / Issue #20: record the source version and applicable admissions pathway. Check application-stage and enrollment-stage claims separately.
- HT-029 / Issue #18: record the first actionable output before retrieval, plus both elapsed-time measurements.
- HT-035 / Issue #10: record an empty tool-event list when no tools ran and verify that the final answer contains none of the requested off-topic artifact.

Add a nearby passing control for each failure class. Keep the prompt, product, model, settings, and context fixed when comparing behavior before and after a patch.

## Timing and response order

Start both timers when the test prompt is submitted. Stop `time_to_first_actionable_seconds` at the first user-visible instruction that a person can act on. A preamble such as “Let me check” is not actionable. Stop `time_to_final_answer_seconds` when the complete final answer is visible.

Record ordered tool and output events. For emergency tests, the immediate general safety direction must precede retrieval or clarification. Campus-specific contacts may follow only after verification.
Only an actionable `user-visible-output` event can stop the first-action timer. Marking a retrieval or tool call actionable does not count. No event may occur after `time_to_final_answer_seconds`.

## Scoring and disposition

Each score is an integer from 0 through 2. `total_0_10` must equal the five component scores. Leave all six score cells blank until review; do not convert missing scores to zero.

A `passed` or `failed` disposition requires both timing measurements, all six scores, a completion timestamp, and the complete final answer. Use `needs-review` while any of those fields is missing.

Use only the controlled values in the schema for critical status, priority, classification, source verification, and disposition. A critical failure is not erased by a high numerical total. Link the issue and PR when they exist.

## Validation and export

Validate a CSV and export normalized JSONL with:

```text
python -m ncfbot human-evaluation --input path/to/round-2.csv --export path/to/round-2.jsonl
```

Validate a JSONL file without exporting it with:

```text
python -m ncfbot human-evaluation --input path/to/round-2.jsonl
```

The command refuses to export if headers, JSON cells, schema fields, score totals, event ordering, or timing relationships are invalid.
