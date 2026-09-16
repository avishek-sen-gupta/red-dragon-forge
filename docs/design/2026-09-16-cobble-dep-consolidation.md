# cobble: Consolidate Build Dependencies into Forge

**Date:** 2026-09-16
**Status:** planned

---

## Problem

cobble maintains its own copies of three build-time dependencies that forge already owns:

| Dependency | cobble's copy | forge's copy |
|---|---|---|
| `proleap-bridge` JAR | `cobble/proleap-bridge/` + submodule `proleap-bridge/proleap-cobol-parser` | `vendor/red-dragon/proleap-bridge/` |
| `jcl-bridge` JAR | `cobble/jcl-bridge/` (vendored source, not a submodule) | `jackal/jcl-bridge/` |
| `hlasm_export` binary | built from submodule `vendor/che-che4z-lsp-for-hlasm` | built from `cicada/third-party/che-che4z-lsp-for-hlasm-fork` |

All three point at the same upstream source at the same pin, but because cobble builds its own
copies, a fresh cobble setup requires running `make tools` inside `~/code/cobble` separately from
the normal forge `make setup`. The goal of this change is to make `make setup` at the forge root
the only setup step needed — after it, `make sym` and `make build` in cobble just work.

There is also a known drift: forge's `proleap-bridge` is ahead of cobble's on two files:

- `AsgSerializer.java` — adds `line_start`/`col_start`/`line_end`/`col_end` source positions to
  paragraph objects.
- `StatementSerializer.java` — adds source positions on statement objects; handles level-88
  condition subscripts (`ConditionNameSubscriptReference`, red-dragon-8u47); serializes
  exponentiation (`**`) as a proper `binop` chain instead of a `getText()` fallback; refactors
  subscript serialization into `serializeSubscripts`; fixes STORE call serialization to use
  `serializeRef`.

All changes are additions. No existing field is removed or renamed, so cobble switching to
forge's JAR is a pure upgrade with no risk of breaking existing graph output.

---

## Phase 1 — Consolidate `jcl-bridge`

No source drift. cobble's copy is vendored source (not a submodule); `diff -rq` produces only a
stray `.claude/` directory difference.

1. Delete `cobble/jcl-bridge/` entirely.
2. In `cobble/Makefile`, change:
   ```makefile
   JCL_BRIDGE_JAR := $(CURDIR)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
   ```
   to:
   ```makefile
   JCL_BRIDGE_JAR := $(CURDIR)/../jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
   ```
3. Remove the jcl-bridge build step from cobble's `jars` Makefile target.

---

## Phase 2 — Consolidate `proleap-bridge`

Forge's copy is ahead; see drift summary above. cobble's submodule becomes dead weight.

1. Remove the `proleap-bridge/proleap-cobol-parser` submodule from cobble:
   ```bash
   git submodule deinit cobble/proleap-bridge/proleap-cobol-parser
   git rm cobble/proleap-bridge/proleap-cobol-parser
   ```
   Remove the corresponding entry from `cobble/.gitmodules`.
2. Delete `cobble/proleap-bridge/` entirely (source + any generated JAR).
3. In `cobble/Makefile`, change:
   ```makefile
   PROLEAP_BRIDGE_JAR := $(CURDIR)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
   ```
   to:
   ```makefile
   PROLEAP_BRIDGE_JAR := $(CURDIR)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
   ```
4. Remove the proleap build steps from cobble's `jars` Makefile target. With both JAR steps gone,
   `jars` and `tools` are now vacuous — remove both targets and their `.PHONY` entries. Update
   cobble's `README.md` `make` target table accordingly.

---

## Phase 3 — Consolidate `hlasm_export`

Same submodule (`avishek-sen-gupta/che-che4z-lsp-for-hlasm`) at the same branch (`krakatoa-1.22.1`)
in both repos. Forge's binary is already built at:
`cicada/third-party/che-che4z-lsp-for-hlasm-fork/build/bin/hlasm_export`.

`cobble/cobble/generate_sym.py` hardcodes the binary path relative to `_REPO_ROOT`
(`Path(__file__).resolve().parent.parent`, i.e. the cobble package root):

```python
_HLASM = (
    _REPO_ROOT / "vendor" / "che-che4z-lsp-for-hlasm" / "build" / "bin" / "hlasm_export"
)
```

Since cobble lives at `forge/cobble/`, `_REPO_ROOT.parent` is the forge root.

1. In `generate_sym.py`, change `_HLASM` to:
   ```python
   _HLASM = (
       _REPO_ROOT.parent
       / "cicada" / "third-party" / "che-che4z-lsp-for-hlasm-fork"
       / "build" / "bin" / "hlasm_export"
   )
   ```
2. Remove the `vendor/che-che4z-lsp-for-hlasm` submodule from cobble:
   ```bash
   git submodule deinit cobble/vendor/che-che4z-lsp-for-hlasm
   git rm cobble/vendor/che-che4z-lsp-for-hlasm
   ```
   Remove the corresponding entry from `cobble/.gitmodules`. If `cobble/vendor/` is then empty,
   remove it too.
3. Remove cobble's `hlasm` Makefile target and its `.PHONY` entry.

---

## Phase 4 — Add `hlasm` build to forge's `make setup`

forge's `make setup` currently: submodules → `make jar` (proleap + jcl bridges) → `uv sync`.
It does not build `hlasm_export`. After Phase 3, cobble depends on forge's binary being present.

1. Add an `hlasm` target to forge's `Makefile`:
   ```makefile
   hlasm:
       cd cicada/third-party/che-che4z-lsp-for-hlasm-fork && BUILD_TYPE=Release bash build.sh --target hlasm_export
   ```
2. Wire it into `setup`:
   ```makefile
   setup:
       git submodule update --init --recursive
       $(MAKE) hlasm
       $(MAKE) jar
       $(MAKE) python
   ```
3. Add `hlasm` to forge's `.PHONY` line.
4. Add it to the `help` target output:
   ```makefile
   @echo "make hlasm     - build hlasm_export from the che-che4z-lsp-for-hlasm submodule"
   ```

---

## Verification

After all four phases:

```bash
# From a clean forge checkout:
make setup
# Expected: submodules fetched, hlasm_export built, both bridge JARs built, uv sync done.
# No separate cd cobble && make tools required.

# BMS symbolic copybook generation for a corpus:
cd cobble
make sym CONFIG=config/prod.local.yaml
# Expected: sym/*.cpy written, no "hlasm_export not built" error.

# Full graph extraction for a corpus:
make build CONFIG=config/prod.local.yaml
# Expected: out/nodes.jsonl + edges.jsonl written cleanly.

# cobble's own test suite:
make test
# Expected: all pass (proleap upgrade is additive; no existing serialized field removed).
```

---

## What stays in cobble's Makefile

After consolidation, cobble's `Makefile` retains: `codegen`, `parser`, `sym`, `csd`, `build`,
`compare`, `verify`, `render`, `render-webgl`, `canonical`, `test`, `fmt`, `lint`, `clean`.
The `tools`, `hlasm`, `jars` targets are removed. `PROLEAP_BRIDGE_JAR` and `JCL_BRIDGE_JAR` at
the top of the file point at forge's paths. `BRIDGE_ENV` is unchanged.
