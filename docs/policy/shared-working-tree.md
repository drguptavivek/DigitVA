---
title: Shared Working Tree Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-18
---

# Shared Working Tree Policy

## Purpose

Several people and agent sessions work in **one checkout of this repository at
the same time**. On 2026-09-18 four sessions held uncommitted work in it
simultaneously.

In that setting, git commands that operate on the working tree are not local
decisions. `git stash`, `git checkout -- .`, `git restore .`, `git reset
--hard` and `git clean` act on *everything dirty*, which includes work nobody
told you about. One `git stash` that day swept 37 files and 1662 insertions
belonging to four sessions.

This is the same class of hazard as
[Migration Chaining Policy](migration-chaining.md) rule 1: an operation that
is perfectly safe alone and destructive when shared.

## Why this failure is invisible

State this before anything else, because it is what stops people noticing:

**Untracked files survive a stash. Edits to tracked files do not.**

So afterwards, new work looks perfectly fine — new modules, new tests, all
present — while modifications to existing files have silently gone. Nothing
appears broken.

The 2026-09-18 incident was found because someone noticed **one missing
function call** in a file they had edited. They had run a full test suite an
hour earlier which would have caught it, had it happened then. Nothing in the
tree announced the loss.

Do not conclude from this that new files are safe generally. They survive a
plain `git stash`; they do not survive everything:

- a plain `git stash` captures modifications to **tracked** files, staged and
  unstaged alike. They are in the stash, and recoverable — that is rule 4.
- `git stash -u` additionally sweeps **untracked** files into the stash.
  Recoverable, but easy to overlook when reading `git stash show --stat`.
- **`git clean` deletes untracked files outright.** No stash, no reflog, no
  recovery. This is the one to fear for new work.
- `git checkout -- .`, `git restore .` and `git reset --hard` discard
  unstaged modifications to tracked files **without stashing them**, and
  those are equally unrecoverable. Content that was *staged* at some point
  may be retrievable with `git fsck --lost-found`, because staging writes it
  to the object store; content that was never staged was never written
  anywhere.

## How to notice

The failure does not announce itself, so the detection is a habit rather than
an alarm: **if something you wrote is missing, check before concluding you
imagined it.**

```bash
git stash list
git reflog
```

Both are non-destructive. A `reset: moving to HEAD` entry in the reflog with
no commit movement is the fingerprint, and it timestamps the event. That is
how the 2026-09-18 incident was traced.

## Rules

### 1. Never run a whole-tree git operation

Prohibited in a shared checkout unless you have confirmed with everyone
working in it. These **destroy or hide** others' work:

- `git stash` (any form)
- `git checkout -- .` / `git checkout .`
- `git restore .`
- `git reset --hard`
- `git clean`

To undo your own edit, **edit the file back**. Do not reach for git: git does
not know which of the dirty files are yours.

`git add .` / `-A` / `-u` belong to a different hazard — they destroy nothing,
they **sweep** others' work into your commit. That is rule 2.

### 2. Stage by explicit path, always

`git add <path> <path>` naming the files you actually changed. A broad
pathspec sweeps other sessions' work into your commit, which is how one
session's half-finished change ends up pushed under another's name.

### 3. Commit only your own files

Before committing, run `git status --short` and confirm every staged path is
yours. If a file you need is also being edited by someone else, say so rather
than committing around them.

### 4. If it has already happened, recover by path — never `git stash pop`

`git stash pop` tries to apply every file in the stash, including other
people's, and will conflict against anything since re-edited in the tree.

Instead, each session recovers only its own files:

```bash
git stash list
git stash show --stat stash@{0}
git checkout stash@{0} -- <your paths>
```

**Prefer never dropping it at all.** Once everyone has recovered, dropping is
the only irreversible operation left in the situation, and it buys nothing: a
stash costs nothing to keep. On 2026-09-18 the only reason the stash still
existed to recover from was a sandbox guard that refused to drop it. Every session will have "verified" it is clear
using reasoning, minutes after an incident, in a tree others are still
editing. If one of them is wrong, the stash is the entire recovery path.

The instinct to tidy up is what caused the incident. Do not let it end it.

### 5. A subagent is never authorised to run one

The rule is not "be careful with git", which nobody can act on. It is:

- a working-tree-touching operation needs the **agreement of everyone in the
  tree**, so only a person coordinating with the others may run one
- **a subagent may never run one**, under any circumstances, because a
  subagent cannot know who else is in the repository

### What it looked like

On 2026-09-18 a subagent working on an unrelated task ran `git stash` **to
compare current behaviour against the `main` baseline**. That is a reasonable
thing to do and an ordinary use of the command. In a private checkout it
would have been harmless.

It swept four sessions' uncommitted work. It then recovered carefully —
restoring every stashed file except one it had collided with, and unstaging
the rest back to plain modifications — but it could not restore work created
*after* the stash, which is how the loss was eventually noticed.

The subagent had no way to know the checkout was shared. The brief it was
given said "do not run git commit" and nothing else.

Note what saved the situation: the stash survived only because a sandbox
guard refused to let the subagent drop it. Not judgement, not this policy —
a tool refusing. The work was one permission check away from being gone,
along with the last trace of it.

Say it explicitly in every subagent brief. A coding agent's default
assumption is that the checkout is its own, and "do not commit" does not
imply "do not stash" — on 2026-09-18 two separate sessions had briefed their
subagents against committing and neither had thought to forbid the rest.

Permitted for a subagent: `status`, `diff`, `log`, `show`. Forbidden: `add`,
`commit`, `reset`, `checkout --`, `restore`, `stash`, `clean`, `rm`. To undo
its own work it edits the file directly.

### 6. Verification reads the committed ref, not the tree

A working tree containing four sessions' uncommitted work does not represent
what anyone else will get. See
[Migration Chaining Policy](migration-chaining.md) rule 5 — the same
reasoning applies to anything you are trying to prove about the repository,
not only to migrations.

## Better than this policy

Every rule above except rule 5 exists only because we are sharing one
checkout. That is a choice, not a fact about the repository.

`git worktree add` gives each session its own working tree and its own index
against the same repository and object store. Separate trees cannot sweep
each other: there is nothing dirty in common to stash, clean or reset.

**If you can give each session its own worktree, do that instead**, and most
of this document becomes unnecessary. It is written for the situation we were
actually in on 2026-09-18, and it should be read as managing a hazard rather
than endorsing the arrangement that creates it.
