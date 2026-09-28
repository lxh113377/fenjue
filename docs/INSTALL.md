# Fenjue operator install (slim)

> Personal setup. Numbers below are 2026-09-23 — re-run gates before quoting.

**What:** one source of truth (`<memory-root>`, `<skills-root>`) shared by every active agent frontend
via junctions — the authoritative count is `endpoints.active` in `eval/truth_constants.json`, read live
by `eval/doc_claim_face.py` (the 2026-09-23 revision of this line asserted a count that had already
drifted, which is why the count is no longer written into prose). Plus a 5-layer skill router,
machine gates and a 7-step loop (memory → prompt tune → clarify → handoff → task card → execute →
feedback + savepoint).

> 下面这两个数是**私有源仓**面（技能库与盲测集都不随对外子集分发），在本报表仓内不可复算：
> 151 skills / blind-test 284 of 284 routing hits。引用前请回源仓重测，别当本仓读数。

> Placeholders: `<memory-root>` / `<skills-root>` = your global memory / skills source dirs; `<repo>` = this repository clone path; `%USERPROFILE%` / `%LOCALAPPDATA%` are expanded by cmd.

## Per-platform guides (copy-paste, Chinese)

- WorkBuddy: `INSTALL-wb.md`
- Codex CLI: `INSTALL-cx.md` (skills are a physical mirror, not a junction)
- Hermes: `INSTALL-hm.md` (per-skill junctions)
- ZCode: `INSTALL-zc.md` (first-level junctions)
- TRAE / OpenCode: no standalone guide — reuse `wf_generic.ps1` (`-Platform tr` / `-Platform oc`)

Each ends with the same two green bars: `check_junction.ps1` 0 anomalies + `verify_truth_consistency.py`
N PASS / 0 FAIL.〔2026-09-29 更正：此句原写 "scripts live in the private repo"，实测两个脚本
`scripts/check_junction.ps1` 与 `eval/verify_truth_consistency.py` **都随对外子集分发**，
在仓内可直接跑（`git ls-files` 命中）；保留原句时点读数以留痕。〕

## Finish a branch

`finish-branch.ps1` + playbook (private repo `scripts/` + `deliverables/`): verify tests → detect env → confirm base → merge / PR / keep menu → clean up (never `--force`; discard only on typed `discard`).

## Lean startup

P0 injects resident skills + TOP15 one-liners only (≤4KB, ~45% call coverage); the rest loads on demand via `unified_router`. Never full-load the library (attention dilutes to ~0.08x).
