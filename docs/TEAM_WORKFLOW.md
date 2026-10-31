# Two-Person Team Workflow: Quick Start

1. Both developers clone the same Git repository and copy this collaboration kit into it.
2. The shared coding-agent prompt is `TEAM_AGENT_PROMPT.md`. Both developers use the exact same prompt.
3. At the start of every coding-agent session, the human says either `I am Friend A.` or `I am Friend B.`.
4. Check `docs/PHASE_STATUS.md` to see whose turn it is. Do not code another person's phase.
5. Work on `hackathon/team-integration`, one phase at a time.
6. The phase owner implements, tests, updates `PHASE_STATUS.md`, appends to `COLLAB_LOG.md`, commits and pushes.
7. The other teammate pulls that exact commit, independently reviews the diff and tests, then records a verdict.
8. If changes are requested, the original owner fixes them. The next phase does not start until the current phase is accepted.
9. Continue with alternating ownership as specified in `docs/TEAM_PHASE_PLAN.md`.

## First run

Friend A starts with:

```text
I am Friend A.
Read TEAM_AGENT_PROMPT.md and the docs listed there. Inspect the repository and start Phase 0 only. Do not begin Phase 1.
```

After Friend A pushes the Phase 0 handoff, Friend B starts with:

```text
I am Friend B.
Read TEAM_AGENT_PROMPT.md. Pull and independently review Friend A's Phase 0 handoff. If it passes, update the collaboration log and start Phase 1. Do not skip the review.
```

The same prompt is used throughout. The role comes from the explicit Friend A/B designation and the current phase status, not from a different prompt for each person.
