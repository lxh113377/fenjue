# Fenjue operator install (slim)

> Personal setup. Numbers below are 2026-09-23 — re-run gates before quoting.

**What:** one source of truth (`<memory-root>`, `<skills-root>`) shared by 8 agent frontends via junctions, plus a 5-layer skill router, 28 machine gates and a 7-step loop (memory → prompt tune → clarify → handoff → task card → execute → feedback + savepoint). 151 skills, blind-test 284/284 routing hits.

> Placeholders: `<memory-root>` / `<skills-root>` = your global memory / skills source dirs; `<repo>` = this repository clone path; `%USERPROFILE%` / `%LOCALAPPDATA%` are expanded by cmd.

## Per-platform guides (copy-paste, Chinese)

- WorkBuddy: `INSTALL-wb.md`
- Codex CLI: `INSTALL-cx.md` (skills are a physical mirror, not a junction)
- Hermes: `INSTALL-hm.md` (per-skill junctions)
- ZCode: `INSTALL-zc.md` (first-level junctions)
- TRAE / OpenCode: no standalone guide — reuse `wf_generic.ps1` (`-Platform tr` / `-Platform oc`)

Each ends with the same two green bars: `check_junction.ps1` 0 anomalies + `verify_truth_consistency.py` N PASS / 0 FAIL (scripts live in the private repo).

## Finish a branch

`finish-branch.ps1` + playbook (private repo `scripts/` + `deliverables/`): verify tests → detect env → confirm base → merge / PR / keep menu → clean up (never `--force`; discard only on typed `discard`).

## Lean startup

P0 injects resident skills + TOP15 one-liners only (≤4KB, ~45% call coverage); the rest loads on demand via `unified_router`. Never full-load the library (attention dilutes to ~0.08x).
