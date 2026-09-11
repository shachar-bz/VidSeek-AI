---
name: open-worktree
description: Open a git worktree in a new VS Code window. Use when the user asks to open/view a worktree in VS Code, or proactively right after finishing all the work for a branch's worktree (per the Branch and Worktree workflow in CLAUDE.md), so the user can review the result in its own window.
---

# Open Worktree in VS Code

Opens a git worktree directory in a **new** VS Code window (`code -n`), without
disturbing whatever window/session is already open for the main repo.

## When to use this

- The user explicitly asks to open a worktree (or "this branch") in VS Code.
- Claude has just finished the work for a branch that has a dedicated worktree
  (per the "Branch and Worktree" rules in CLAUDE.md) and is about to report
  the work as done — open the window as part of wrapping up, not mid-task.

Do not use this for the main repo checkout, and do not use it repeatedly
during a single piece of work — once per finished branch/worktree is enough.

## Steps

1. **Resolve the target worktree path.**
   - If the user named a branch or gave a path, resolve it with:
     `git worktree list --porcelain`
     Look for the block whose `branch` line matches (`refs/heads/<name>`) or
     whose `worktree` line matches the given path.
   - Otherwise, if Claude is currently working inside a linked worktree
     (not the main checkout), use that directory. Detect a linked worktree by
     comparing:
     `git rev-parse --git-dir` vs `git rev-parse --git-common-dir`
     — if they differ, the current directory is a linked worktree.
   - If neither applies (e.g. currently in the main repo checkout with no
     branch specified), list worktrees with `git worktree list` and ask the
     user which one they mean instead of guessing.

2. **Validate** the resolved path exists and is not the main repo's own
   working directory (skip opening if it resolves to the main checkout —
   that already has a window/session open).

3. **Open it**: run `code -n "<worktree-path>"` (the `-n` flag forces a new
   window rather than reusing one). This returns immediately; no need to wait
   for it or check its output beyond a nonzero exit code.

4. Briefly confirm to the user which worktree/branch was opened.
