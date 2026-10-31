# Handoff Template

Copy the relevant section into `docs/COLLAB_LOG.md`. Do not overwrite previous entries.

## Implementation handoff: Phase [N] - [Title]

- Date/time (ISO 8601):
- Implementation owner: Friend [A/B]
- Assigned reviewer: Friend [A/B]
- Branch: `hackathon/team-integration`
- Base commit SHA:
- Result commit SHA:
- Status: `AWAITING_REVIEW`

### Scope completed

- 

### Files changed

- 

### Tests and commands actually run

| Command | Result | Notes |
|---|---|---|
| `pytest ...` | PASS/FAIL/NOT RUN | |
| `ruff check .` | PASS/FAIL/NOT RUN | |
| CLI smoke test | PASS/FAIL/NOT RUN | |

### Evidence of behavior

Describe a reproducible input/command and the observed output. Avoid statements such as "works" without evidence.

### Deviations and decisions

- Decision record references:
- Public contract changes:
- Architecture deviations:

### Known issues / unverified areas

- 

### Reviewer checklist

- [ ] Inspect diff and changed files.
- [ ] Run the listed tests independently.
- [ ] Check phase exit criteria.
- [ ] Check architectural boundaries.
- [ ] Check no secrets or generated junk were committed.

### Next phase

- Phase:
- Owner:
- Reviewer:

---

## Review verdict: Phase [N] - [Title]

- Date/time (ISO 8601):
- Reviewer: Friend [A/B]
- Implementation owner: Friend [A/B]
- Commit reviewed:
- Status: `VERIFIED` / `CHANGES_REQUESTED` / `ACCEPTED_WITH_KNOWN_ISSUES`

### Independent checks

| Command/check | Result | Notes |
|---|---|---|
| Diff inspection | PASS/FAIL | |
| Focused tests | PASS/FAIL | |
| Full tests | PASS/FAIL/NOT RUN | |
| CLI/demo run | PASS/FAIL/NOT APPLICABLE | |

### Findings

- `[BLOCKER]` ...
- `[MAJOR]` ...
- `[MINOR]` ...
- `[NIT]` ...

Write `None` if there are no findings at a severity level.

### Verdict rationale

Explain why this phase is accepted or what must change before acceptance.

### Next phase authorization

- Next phase:
- Next owner:
- Authorized to start: YES / NO

---
