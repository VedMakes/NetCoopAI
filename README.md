# NetCoop Team Collaboration Kit

This package coordinates two developers and their coding agents through alternating implementation phases and independent reviews.

## Files to place in the repository

- `TEAM_AGENT_PROMPT.md`: the one shared prompt. Both people use this exact file and identify themselves as Friend A or Friend B at the start of each session.
- `docs/TEAM_PHASE_PLAN.md`: phase boundaries, ownership, estimates and exit criteria.
- `docs/PHASE_STATUS.md`: current phase and handoff status.
- `docs/COLLAB_LOG.md`: append-only implementation and review history.
- `docs/HANDOFF_TEMPLATE.md`: required handoff/review record.
- `docs/DECISIONS.md`: architecture and contract decision log.
- `docs/TEAM_WORKFLOW.md`: short human quick-start guide.
- `docs/ARCHITECTURE.md`: detailed architecture baseline.
- `docs/IMPLEMENTATION_PLAYBOOK.md`: product and CLI implementation requirements.
- `docs/INTERAGENT_COMMS.md`: detailed inter-agent communication contract instructions.
- `.github/PULL_REQUEST_TEMPLATE.md`: optional PR template.
- `reference/NetCoop_Challenge_Brief.pdf`: the supplied challenge statement used as the requirements baseline.

## Install into an existing repository

Copy the contents of this directory into the root of the NetCoop repository, preserving the directory structure. Review any existing `docs/` files before overwriting them. If equivalent documents already exist, merge carefully and preserve useful project-specific material.

Then follow `docs/TEAM_WORKFLOW.md`.
