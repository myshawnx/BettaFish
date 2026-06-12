# Agent Instructions

## Git and Sandbox Policy

This repository may be used from Codex in `workspace-write` mode. In that
environment the working tree is writable, but `.git` can be mounted read-only by
the Codex sandbox even when the user's real WSL checkout is fully writable.

Treat a `Read-only file system` error under `.git` as a Codex sandbox limitation,
not as evidence that the user's real WSL repository is broken.

## Commands That Must Be Elevated

Do not run commands that write `.git` in the normal sandbox. Request elevated
permissions for these commands instead:

- `git add`
- `git commit`
- `git branch`
- `git checkout` / `git switch`
- `git merge` / `git rebase`
- `git reset`
- `git stash`
- `git tag`
- `git update-ref`
- `git fetch` / `git pull`
- `git push`

`git push` must also be elevated because, after the remote update succeeds, Git
may update local tracking refs under `.git/refs/remotes`.

Prefer per-command escalation over broad access. Do not ask the user to switch
the whole session to `danger-full-access` just to commit or push.

## Normal Workflow

1. Edit source files normally in the workspace.
2. Run local checks/tests normally when they do not need `.git` or network
   access. Escalate only if a required command fails due to sandbox or network
   restrictions.
3. Inspect changes with read-only Git commands such as `git diff`, `git log`,
   `git show`, and `git remote -v`.
4. When the user asks for commit/push, or the task explicitly includes it,
   request elevated permissions for:
   - `git add <files>`
   - `git commit -m "<message>"`
   - `git push origin HEAD:<branch>`
5. After pushing, verify the branch state. If local tracking refs cannot be
   updated due to sandbox restrictions, use `git ls-remote` to verify the remote
   result and tell the user they can run Fetch From All Remotes in the real WSL
   environment.

## Cleanup Rules

Do not leave test refs, temporary branches, or temporary files behind. If a
temporary remote branch is created for testing, delete it before finishing.

Never revert user changes unless the user explicitly asks for it.
