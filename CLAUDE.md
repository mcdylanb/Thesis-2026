## Current status: read first

The TechHub Calibration session (29-30 Oct 2026) worked as a pilot only. With
corner Anchors the Sniper can run in 0.5 % of Beacon windows, so the layout
must change and the session must be recorded again before the Test-position
day. Findings, where every number comes from, and the next steps:
`docs/findings/2026-11-01-techhub-calibration.md`. Work is tracked in
GitHub issue #57 and its sub-issues.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for `mcdylanb/Thesis-2026` via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage labels are used as-is (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Tooling

Tool install (`uv`, `gh`, `make`, `latexmk`, Arduino IDE) and the Makefile targets are in `README.md`. Run `make test` before committing Python changes.
