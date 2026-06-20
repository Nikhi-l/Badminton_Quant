# Branching

Trunk-based, one task per branch (pragmatic subset of the v2 harness).

```
main                                   # protected, always releasable
feat/TASK-001-shuttle-follow-camera    # short-lived feature branch
fix/TASK-0NN-…                          # bugfix branch
chore/TASK-0NN-…                        # maintenance / scaffolding
spike/TASK-0NN-…                        # research, not merged directly
```

## Rules
- **No agent works directly on `main`.**
- One task → one branch → one PR back to `main`.
- Branch names: `<type>/TASK-NNN-slug` (`type` ∈ feat | fix | chore | spike).
- Keep branches short-lived; rebase/merge `main` in if they age.
- No force-push to `main`.
- Merge only after `./scripts/check.sh` passes (or the gap is documented in the
  task's cycle-log entry).

## Not adopted yet (add when needed)
Worktrees, mission/epic branches, patch files, CI gating. The PRD remediation
queue will call these out if/when a migration warrants them.

## Commit message convention
`<type>: <imperative summary>` matching the branch type, e.g.
`feat: make the virtual camera follow the shuttle`. End commit bodies with the
Co-Authored-By trailer.
