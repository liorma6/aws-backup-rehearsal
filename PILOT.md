# Proposed engineering evaluation

## Problem hypothesis

Some cloud-backup application failure paths may be slow or awkward to reproduce against live cloud infrastructure. A narrow emulator-based test harness could make selected development checks easier to repeat.

This is a hypothesis. No customer interviews, internal Eon workflow review, savings measurement, or buyer commitment has occurred.

## Current deliverable

An independent S3 sample workflow with six repeatable scenarios, explicit injected-error provenance, content-integrity checks, isolated synthetic resources, portable reports and an official-AWS-Emulator CI job. Consult the linked Actions run for executed results rather than treating a proposed test as a verified capability.

The sample contains no Eon integration. It does not claim to replace Eon's existing backup or restore verification. Eon publicly describes restore verification in its [technical article](https://www.eon.io/blog/backup-restore-verification); the proposed discussion is about development-test reproducibility around a selected workflow.

## Suggested first discussion

A 20-minute conversation with the engineering, infrastructure or developer-productivity owner:

1. Which single AWS integration test is slow, flaky or hard to reproduce today?
2. Which exact APIs and failure paths does it use?
3. Can that code run against a configurable SDK endpoint with synthetic data?
4. What existing test already covers it, and what would be meaningfully better?
5. Who owns acceptance and any purchasing decision?

## Bounded follow-on pilot, if there is a match

- One agreed workflow, initially S3 only.
- Synthetic fixtures; no production access required for the first iteration.
- Map the workflow's API calls against the emulator's current behavior.
- Integrate an agreed application entry point, rather than simulate a partner integration that does not exist.
- Compare repeated execution with the team's existing development test on the same machine class and workload. Record setup time, test time, retry behavior and reproduction success.
- Run the necessary real-AWS comparison in a separately approved sandbox owned by the partner; the current CLI intentionally cannot target AWS.
- Deliver code, run instructions, request traces, explicit coverage gaps and a short evidence review.

## Proposed acceptance criteria

| Criterion | Evidence |
|---|---|
| Reproducible outcomes | Agreed scenarios produce the same assertions and retry counts across repeated runs |
| Useful failure detection | A deliberately broken workflow fails the relevant check; the corrected workflow passes |
| Visible boundaries | Injected, emulated, unsupported and real-cloud-verified behavior are distinguished |
| Practical adoption | The selected test can run in the team's CI without production credentials |
| Measurable value | A before/after comparison supports a jointly chosen benefit; no savings figure is preclaimed |

## Commercial status

This prototype is an exploratory conversation starter. Scope, compensation, licensing, support and delivery dates for any follow-on work remain to be agreed; no offer is binding and no partnership is implied.

Contact: [Lior Mashiach on GitHub](https://github.com/liorma6) · [LinkedIn](https://www.linkedin.com/in/lior-mashiach/)
