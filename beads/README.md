# beads/ — version-controlled issue graph

`issues.jsonl` is a tracked snapshot of the Beads issue graph (epics, stories, status, and
**all dependency edges**: parent-child, blocks, relates-to). It is the source of truth for the
backlog *in git*.

| Path | Tracked? | Role |
|---|---|---|
| `.beads/` | no (gitignored) | local Dolt working DB — rebuildable |
| `beads/issues.jsonl` | **yes** | portable, diffable snapshot |

This repo uses the **manual-export** model (not beads' native Dolt-over-git-remote sync):
`core.hooksPath` is the default `.git/hooks`, and `.beads/` is gitignored.

## Workflow

**Before committing any issue change**, regenerate and stage the snapshot — this is a
deliberate pre-commit *step*, NOT a git hook (a hook regenerating the file mid-commit would
leave the staged snapshot stale / fight pre-commit's stash-restore):

```bash
bd export -o beads/issues.jsonl && git add beads/issues.jsonl
```

The export is sorted by issue id with sorted keys, so diffs show only real changes.

## Fresh clone

Rebuild the local Dolt DB from the snapshot, then use `bd` as normal:

```bash
bd import beads/issues.jsonl
bd list
```
