# Graph-Analysis-Core Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the VM-free static-analysis core that the knowledge-graph pipeline needs out of six "fat" files across red-dragon and cicada into clean leaf modules, with the fat files re-exporting/delegating so every existing consumer and behavior is unchanged.

**Architecture:** Per file, lift the light analysis-core into a new leaf module; leave the heavy machinery (VM/lowering/tree-sitter/IR types) where it is; the fat file re-exports (constants, types, dispatcher, frontend_extension) or delegates (imports) to the leaf. `flow_map` is the one genuine restructure: split verb *acquisition* (lowering, stays production-only) from graph *building* (shared leaf, verbs-as-data). Nothing changes signature or behavior.

**Tech Stack:** Python 3.13, `uv`, pytest, Lark, tree-sitter, `import-linter` (`lint-imports`), git submodules (`vendor/red-dragon`).

**Design spec:** `docs/superpowers/specs/2026-07-09-graph-analysis-core-decoupling-design.md`

## Global Constraints

- **Zero behavior change.** Every edit is a pure move + re-export/delegate (except `flow_map`, a pure reorganization of already-separated phases). No logic is rewritten. The graph output stays **449 nodes / 803 edges**.
- **Re-export shims are permanent.** Do NOT migrate any import site. The ~215 importers of `interpreter.constants` and ~24 of `interpreter.project.types` stay untouched; `from interpreter.constants import Language` etc. must keep resolving.
- **Leaf modules are VM/lowering/tree-sitter-free.** Each new leaf imports only stdlib + Lark + sibling leaf vocabulary. This is what makes them byte-for-byte copyable by the graph pipeline.
- **red-dragon changes live in `~/code/red-dragon`** (the canonical clone), NOT in `vendor/red-dragon` (the read-through submodule). Commit/push there, then bump the submodule pointer in `red-dragon-forge`.
- **cicada changes live in `red-dragon-forge/cicada/`.**
- **import-linter must stay green.** New leaf modules and re-export edges must not introduce a forbidden import path. The only contract that needs editing is red-dragon's `cobol-isolation` (Task 1).
- **Tooling invocation:** red-dragon → `uv run python -m pytest …`; cicada → `uv run --no-sync python -m pytest …` (per `cicada/CLAUDE.md` — a plain `uv run` rebuilds the red-dragon editable wheel).
- **Do not commit/push without following the conservative git profile** — but this plan's tasks each end in a commit in the owning repo, matching the design's cross-repo execution. Ask before the cross-repo *push* + submodule bump (Tasks 4a, 6a, 7) if the active profile requires it.

---

## File Structure

**red-dragon (`~/code/red-dragon/`):**
- Create `interpreter/language.py` — `Language` enum leaf (Task 2)
- Create `interpreter/project/import_types.py` — `ImportRef` + `ImportKind` leaf (Task 3)
- Create `interpreter/project/cobol_imports.py` — COBOL COPY/CALL extractor leaf (Task 4)
- Create `interpreter/frontend_extension_lowering.py` — `RedDragonExtensionLoweringStrategy` (Task 1)
- Modify `interpreter/constants.py`, `interpreter/project/types.py`, `interpreter/project/imports.py`, `interpreter/frontend_extension.py`, `.importlinter`

**cicada (`red-dragon-forge/cicada/`):**
- Create `cics/csd_parse.py` — `parse_csd`/`parse_csd_files` + CSD grammar leaf (Task 5)
- Create `cics/flow_graph_core.py` — verbs-as-data graph builder leaf (Task 6)
- Create `cics/verb_source_lowering.py` — lowering verb-source driver (Task 6)
- Modify `cics/dispatcher.py`, `cics/flow_map.py`

**red-dragon-forge (root):**
- Modify `vendor/red-dragon` submodule pointer, `experiments/standalone-graph/port/**` (Task 7)

---

## Task 1: Split `frontend_extension.py` — move the lowering strategy to its own module

**Files:**
- Create: `~/code/red-dragon/interpreter/frontend_extension_lowering.py`
- Modify: `~/code/red-dragon/interpreter/frontend_extension.py`
- Modify: `~/code/red-dragon/.importlinter`
- Test: `~/code/red-dragon/tests/unit/test_dialect_parser_seam.py`, `tests/unit/cobol/test_dialect_parser.py`

**Interfaces:**
- Produces: `interpreter.frontend_extension_lowering.RedDragonExtensionLoweringStrategy` (Protocol, `runtime_checkable`), re-exported from `interpreter.frontend_extension` so `from interpreter.frontend_extension import RedDragonExtensionLoweringStrategy` still resolves. `DialectParser` / `NullDialectParser` stay in `frontend_extension`.

- [ ] **Step 1: Confirm the current regression tests pass (baseline)**

Run: `cd ~/code/red-dragon && uv run python -m pytest tests/unit/test_dialect_parser_seam.py tests/unit/cobol/test_dialect_parser.py -q`
Expected: PASS (record the count).

- [ ] **Step 2: Find who imports `RedDragonExtensionLoweringStrategy`**

Run: `cd ~/code/red-dragon && grep -rn 'RedDragonExtensionLoweringStrategy' interpreter tests --include='*.py' | grep -v frontend_extension.py`
Expected: every hit imports it from `interpreter.frontend_extension` (or is a structural user). Note them — the re-export in Step 4 must keep them working. If any import it from a different path, adjust that path's expectation accordingly (do not migrate; just confirm the re-export covers them).

- [ ] **Step 3: Create the new lowering module**

Create `~/code/red-dragon/interpreter/frontend_extension_lowering.py` with the `RedDragonExtensionLoweringStrategy` Protocol **moved verbatim** from `frontend_extension.py` (current lines 23–46), plus the two `TYPE_CHECKING` imports it needs (current lines 18–20):

```python
# pyright: standard
"""RedDragonExtensionLoweringStrategy — the injectable extension-lowering seam.

Split out of interpreter.frontend_extension so this module (the only one that
references interpreter.cobol.emit_context / sectioned_layout) is separate from
the parse-time DialectParser seam, which is VM/lowering-free and copyable by
static-analysis consumers. frontend_extension re-exports this name for
backward compatibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from interpreter.cobol.emit_context import EmitContext
    from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout


@runtime_checkable
class RedDragonExtensionLoweringStrategy(Protocol):
    """One injectable extension-lowering strategy (CICS, SQL, …)."""

    def handles(self, stmt: Any) -> bool:
        """True if this strategy owns ``stmt`` (e.g. isinstance(stmt, YourDialectStatement))."""
        ...

    def preprocess_program_dict(self, data: dict) -> dict:
        """Transform the raw bridge JSON dict before generic COBOL parsing.
        Return ``data`` unchanged for a no-op."""
        ...

    def on_procedure_entry(
        self, ctx: "EmitContext", materialised: "MaterialisedSectionedLayout"
    ) -> None:
        """Called once at the start of the procedure division."""
        ...

    def lower(
        self, ctx: "EmitContext", stmt: Any, materialised: "MaterialisedSectionedLayout"
    ) -> None:
        """Lower one extension statement to IR."""
        ...
```

- [ ] **Step 4: Trim `frontend_extension.py` to the DialectParser seam + re-export**

In `~/code/red-dragon/interpreter/frontend_extension.py`: delete the `RedDragonExtensionLoweringStrategy` class (lines 23–46) and the now-unused `TYPE_CHECKING` block (lines 18–20) and the `dataclass`/`TYPE_CHECKING` imports that are no longer used. Keep `DialectParser` and `NullDialectParser`. Add the re-export near the top (after `from __future__`):

```python
from interpreter.frontend_extension_lowering import (
    RedDragonExtensionLoweringStrategy as RedDragonExtensionLoweringStrategy,
)
```

Keep the remaining imports `DialectParser`/`NullDialectParser` need: `from dataclasses import dataclass`, `from typing import Any, Protocol, runtime_checkable`. Update the module docstring's first line to mention the seam now re-exports the strategy.

- [ ] **Step 5: Repoint the `cobol-isolation` ignore_imports in `.importlinter`**

In `~/code/red-dragon/.importlinter`, under `[importlinter:contract:cobol-isolation]`, change the two frontend_extension ignore lines to the new module:

```ini
    interpreter.frontend_extension_lowering -> interpreter.cobol.emit_context
    interpreter.frontend_extension_lowering -> interpreter.cobol.sectioned_layout
```

(Replace the existing `interpreter.frontend_extension -> interpreter.cobol.emit_context` and `... -> interpreter.cobol.sectioned_layout` lines. The `interpreter.frontend -> interpreter.cobol.*` lines are unaffected — leave them.)

- [ ] **Step 6: Run import-linter**

Run: `cd ~/code/red-dragon && uv run lint-imports`
Expected: all contracts kept (including `cobol-isolation`). If `cobol-isolation` breaks, the ignore repoint in Step 5 is wrong — verify the TYPE_CHECKING imports actually moved to `frontend_extension_lowering`.

- [ ] **Step 7: Run the regression tests**

Run: `cd ~/code/red-dragon && uv run python -m pytest tests/unit/test_dialect_parser_seam.py tests/unit/cobol/test_dialect_parser.py tests/unit/project/test_coprocessor_compile.py -q`
Expected: PASS, same count as Step 1.

- [ ] **Step 8: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/frontend_extension.py interpreter/frontend_extension_lowering.py .importlinter
git commit -m "refactor: split RedDragonExtensionLoweringStrategy into frontend_extension_lowering"
```

---

## Task 2: Extract `Language` enum into `interpreter/language.py`

**Files:**
- Create: `~/code/red-dragon/interpreter/language.py`
- Modify: `~/code/red-dragon/interpreter/constants.py`
- Test: `~/code/red-dragon/tests/unit/project/test_all_language_imports.py`

**Interfaces:**
- Produces: `interpreter.language.Language` (StrEnum, 16 members), re-exported from `interpreter.constants` so `from interpreter.constants import Language` still resolves.

- [ ] **Step 1: Create the leaf module**

Create `~/code/red-dragon/interpreter/language.py` with the `Language` enum **moved verbatim** from `constants.py` (current lines 11–34):

```python
# pyright: standard
"""The Language enum — the bounded set of supported source languages.

A leaf-vocabulary module (stdlib-only) so static-analysis consumers that need
only the language tag never import the heavier interpreter.constants (which
pulls in interpreter.type_name for the IR type ontology). interpreter.constants
re-exports Language for backward compatibility.
"""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    """Bounded set of supported source languages.

    Each member's value is the tree-sitter language name string, so
    ``Language.PYTHON == "python"`` is ``True`` and members pass through
    directly to ``tree_sitter_language_pack.get_parser()``.
    """

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    RUBY = "ruby"
    GO = "go"
    PHP = "php"
    CSHARP = "csharp"
    C = "c"
    CPP = "cpp"
    RUST = "rust"
    KOTLIN = "kotlin"
    SCALA = "scala"
    LUA = "lua"
    PASCAL = "pascal"
    COBOL = "cobol"
```

- [ ] **Step 2: Replace the enum in `constants.py` with a re-export**

In `~/code/red-dragon/interpreter/constants.py`, delete the `Language` class body (lines 11–34) and add the re-export after the existing `from interpreter.type_name import TypeName` import:

```python
from interpreter.language import Language as Language
```

Leave everything else (all the prefix consts, `SUPPORTED_DETERMINISTIC_LANGUAGES` at line 64 which uses `Language`, `LLMProvider`, `CanonicalLiteral`, `Variance`, `FoundationTypeName`, …) exactly as is. `SUPPORTED_DETERMINISTIC_LANGUAGES` now reads the re-exported `Language` — no change needed.

- [ ] **Step 3: Sanity-check the re-export resolves and is the same object**

Run: `cd ~/code/red-dragon && uv run python -c "from interpreter.constants import Language as A; from interpreter.language import Language as B; assert A is B; assert A.COBOL == 'cobol'; print('ok', len(list(A)))"`
Expected: `ok 16`

- [ ] **Step 4: Run import-linter and a language-touching test**

Run: `cd ~/code/red-dragon && uv run lint-imports && uv run python -m pytest tests/unit/project/test_all_language_imports.py -q`
Expected: contracts kept; tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/language.py interpreter/constants.py
git commit -m "refactor: extract Language enum into interpreter.language leaf module"
```

---

## Task 3: Extract `ImportRef`/`ImportKind` into `interpreter/project/import_types.py`

**Files:**
- Create: `~/code/red-dragon/interpreter/project/import_types.py`
- Modify: `~/code/red-dragon/interpreter/project/types.py`
- Test: `~/code/red-dragon/tests/unit/project/test_import_extraction.py`, `tests/unit/project/test_import_stub_dropping.py`

**Interfaces:**
- Produces: `interpreter.project.import_types.ImportRef` (frozen dataclass) and `ImportKind` (Enum), re-exported from `interpreter.project.types` so `from interpreter.project.types import ImportRef, ImportKind` still resolves. Consumed by Task 4 (`cobol_imports` imports from here, not from the fat `types`).

- [ ] **Step 1: Create the leaf module**

Create `~/code/red-dragon/interpreter/project/import_types.py` with `ImportKind` (current `types.py` lines 44–52) and `ImportRef` (current lines 58–88) **moved verbatim**, plus only the stdlib imports they need:

```python
# pyright: standard
"""ImportRef / ImportKind — the import-statement vocabulary.

A leaf module (stdlib-only) so import-extraction code (interpreter.project.
cobol_imports and the tree-sitter extractors) and static-analysis consumers can
depend on this without pulling in the IR/CFG-heavy interpreter.project.types
(ExportTable / ModuleUnit / LinkedProgram). types re-exports both names.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ImportKind(Enum):
    """The mechanism used by an import statement."""

    IMPORT = "import"
    INCLUDE = "include"
    USE = "use"
    REQUIRE = "require"
    MOD = "mod"
    USING = "using"


@dataclass(frozen=True)
class ImportRef:
    """A single import statement's information.

    Represents what the source code *says*, not where the target *is*.
    Resolution (ImportRef → file path) is handled separately by ImportResolver.

    Fields:
        source_file:    Path of the file containing this import statement.
        module_path:    The module/package path as written in source.
                        Examples: "os.path", "./utils", "com.example.Utils",
                        "crate::utils", "stdio.h", "fmt".
        names:          Specific names imported. Empty tuple = import the module
                        itself. ("*",) = wildcard import.
        is_relative:    Whether this is a relative import.
        relative_level: Number of parent levels for relative imports
                        (Python's ``from ..`` is 2, ``from .`` is 1, absolute is 0).
        is_system:      Whether this is a standard library / system import.
        kind:           Import mechanism.
                        "import" | "include" | "use" | "require" | "mod" | "using"
        alias:          Optional alias name (``import X as Y``).
    """

    source_file: Path
    module_path: str
    names: tuple[str, ...] = ()
    is_relative: bool = False
    relative_level: int = 0
    is_system: bool = False
    kind: ImportKind = ImportKind.IMPORT
    alias: str | None = None
```

- [ ] **Step 2: Replace the two classes in `types.py` with a re-export**

In `~/code/red-dragon/interpreter/project/types.py`, delete the `ImportKind` class (lines 44–52) and the `ImportRef` class (lines 58–88) along with their `# ── Import kind ──`/`# ── ImportRef ──` section banners. Add the re-export near the top imports:

```python
from interpreter.project.import_types import (
    ImportKind as ImportKind,
    ImportRef as ImportRef,
)
```

`CyclicImportError` stays. Keep `from enum import Enum` only if still used elsewhere in the file (it is not, after removing `ImportKind` — remove it if unused; `ExportTable`/`ModuleUnit`/`LinkedProgram` don't use `Enum`). `ModuleUnit.imports` (line 144) and `LinkedProgram.unresolved_imports` (line 179) reference `ImportRef` via the re-export — no change.

- [ ] **Step 3: Sanity-check the re-export**

Run: `cd ~/code/red-dragon && uv run python -c "from interpreter.project.types import ImportRef as A, ImportKind as B; from interpreter.project.import_types import ImportRef as C, ImportKind as D; assert A is C and B is D; print('ok', B.INCLUDE.value)"`
Expected: `ok include`

- [ ] **Step 4: Run import-linter and the import-model tests**

Run: `cd ~/code/red-dragon && uv run lint-imports && uv run python -m pytest tests/unit/project/test_import_extraction.py tests/unit/project/test_import_stub_dropping.py -q`
Expected: contracts kept; tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/project/import_types.py interpreter/project/types.py
git commit -m "refactor: extract ImportRef/ImportKind into interpreter.project.import_types leaf"
```

---

## Task 4: Extract the COBOL import extractor into `interpreter/project/cobol_imports.py`

**Files:**
- Create: `~/code/red-dragon/interpreter/project/cobol_imports.py`
- Modify: `~/code/red-dragon/interpreter/project/imports.py`
- Test: `~/code/red-dragon/tests/unit/project/test_cobol_imports.py`, `tests/unit/project/test_import_extraction.py`, `tests/unit/project/test_all_language_imports.py`

**Interfaces:**
- Consumes: `interpreter.project.import_types.ImportRef`/`ImportKind` (Task 3).
- Produces: `interpreter.project.cobol_imports.extract_cobol_imports(source: bytes, source_file: Path) -> list[ImportRef]` (today's private `_extract_cobol_imports`, made public). The fat `imports.py` keeps its 3-arg `extract_imports(source, source_file, language)` dispatcher and delegates the COBOL branch to this. The graph pipeline copies this leaf.

- [ ] **Step 1: Verify the COBOL symbols are private (no external importer)**

Run: `cd ~/code/red-dragon && grep -rn '_extract_cobol_imports\|_COBOL_IMPORT_GRAMMAR\|_CobolImportTransformer\|_strip_cobol_comment_lines\|_cobol_import_parser' interpreter tests --include='*.py' | grep -v 'project/imports.py'`
Expected: no external references (only `imports.py` defines/uses them). If any external reference exists, note it — the delegation must keep it working (it imports from `cobol_imports` instead).

- [ ] **Step 2: Baseline the COBOL extractor test**

Run: `cd ~/code/red-dragon && uv run python -m pytest tests/unit/project/test_cobol_imports.py -q`
Expected: PASS (record count). This test needs no bridge JAR (pure Lark).

- [ ] **Step 3: Create the leaf module**

Create `~/code/red-dragon/interpreter/project/cobol_imports.py` with the COBOL grammar/transformer/helpers **moved verbatim** from `imports.py` (current lines 939–1021), the private `_extract_cobol_imports` renamed to public `extract_cobol_imports`:

```python
# pyright: standard
"""COBOL COPY/CALL import extraction — a light Lark grammar over raw bytes.

A leaf module: COBOL is parsed by ProLeap (not tree-sitter), and COPY/CALL are
recovered from the raw source, so this path shares nothing with the tree-sitter
extractors in interpreter.project.imports. Lifted here so static-analysis
consumers (and the fat imports.extract_imports dispatcher) can use it without
the tree-sitter parser factory. Imports only stdlib + Lark + the import
vocabulary leaf.
"""

from __future__ import annotations

from pathlib import Path

from lark import Lark, Transformer as LarkTransformer

from interpreter.project.import_types import ImportKind, ImportRef

_COBOL_IMPORT_GRAMMAR = r"""
    start: item*
    item: copy_stmt | call_stmt | noise

    copy_stmt: COPY_STMT
    call_stmt: CALL_STMT
    noise:     STRING | WORD | PUNCT

    COPY_STMT.3: /COPY[ \t]+[A-Za-z0-9][\w-]*/i
    CALL_STMT.3: /CALL[ \t]+(?:'[^']*'|"[^"]*")/i
    STRING.2:    /'[^']*'|"[^"]*"/
    WORD.1:      /[A-Za-z0-9][\w-]*/
    PUNCT:       /[^\s'"A-Za-z0-9]+/

    %ignore /\s+/
"""

_cobol_import_parser = Lark(_COBOL_IMPORT_GRAMMAR, parser="lalr")


class _CobolImportTransformer(LarkTransformer):
    def start(self, items: list) -> list[tuple[str, str]]:
        return [item for item in items if item is not None]

    def item(self, items: list) -> tuple[str, str] | None:
        return items[0]

    def copy_stmt(self, items: list) -> tuple[str, str]:
        # COPY_STMT token is e.g. "COPY CUSTOMER-RECORD" — name is the last word
        return ("COPY", str(items[0]).split()[-1])

    def call_stmt(self, items: list) -> tuple[str, str]:
        # CALL_STMT token is e.g. "CALL 'SUBPROG'" — extract between quotes
        raw = str(items[0])
        q = "'" if "'" in raw else '"'
        return ("CALL", raw[raw.index(q) + 1 : raw.rindex(q)])

    def noise(self, _: list) -> None:
        return None


def _strip_cobol_comment_lines(text: str) -> str:
    """Remove COBOL comment lines before grammar tokenisation.

    - Fixed-format: column-7 indicator '*' or '/' (index 6).
    - Free-format: trimmed line starts with '*>'.

    Must run before the grammar because %ignore /\\s+/ strips positional
    whitespace, making column-7 anchoring impossible inside the tokeniser.
    """
    clean: list[str] = []
    for line in text.splitlines():
        if len(line) > 6 and line[6] in ("*", "/"):
            continue
        if line.lstrip().startswith("*>"):
            continue
        clean.append(line)
    return "\n".join(clean)


def extract_cobol_imports(source: bytes, source_file: Path) -> list[ImportRef]:
    """Extract COPY and CALL statements from COBOL source.

    Uses a light Lark grammar so keywords inside string literals are
    consumed as opaque STRING tokens and never produce false imports.
    """
    text = _strip_cobol_comment_lines(source.decode("utf-8", errors="replace"))
    pairs: list[tuple[str, str]] = _CobolImportTransformer().transform(
        _cobol_import_parser.parse(text)
    )
    return [
        ImportRef(
            source_file=source_file,
            module_path=name,
            kind=ImportKind.INCLUDE if kind == "COPY" else ImportKind.REQUIRE,
        )
        for kind, name in pairs
    ]
```

- [ ] **Step 4: Delegate the COBOL branch in `imports.py`**

In `~/code/red-dragon/interpreter/project/imports.py`:
1. Delete the moved block (current lines 939–1021: `_COBOL_IMPORT_GRAMMAR` through `_extract_cobol_imports`). Keep the `# ── Shared helpers ──` section (`_extract_string_content`, `_find_nodes_by_type` at 1022+) and `_EXTRACTORS`.
2. Add the delegation import near the top (after `from interpreter.project.types import ImportKind, ImportRef`):

```python
from interpreter.project.cobol_imports import extract_cobol_imports
```

3. Change the COBOL branch of `extract_imports` (current line ~42) to call the delegate:

```python
    if language == Language.COBOL:
        return extract_cobol_imports(source, source_file)
```

Leave the tree-sitter dispatch, `_parser_factory`, and all per-language extractors unchanged.

- [ ] **Step 5: Run the COBOL + full import-extraction tests**

Run: `cd ~/code/red-dragon && uv run python -m pytest tests/unit/project/test_cobol_imports.py tests/unit/project/test_import_extraction.py tests/unit/project/test_all_language_imports.py -q`
Expected: PASS, same COBOL count as Step 2.

- [ ] **Step 6: Run import-linter**

Run: `cd ~/code/red-dragon && uv run lint-imports`
Expected: contracts kept (`cobol_imports` is under `interpreter.project`, same contract exposure as before).

- [ ] **Step 7: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/project/cobol_imports.py interpreter/project/imports.py
git commit -m "refactor: extract COBOL import extractor into interpreter.project.cobol_imports leaf"
```

---

## Task 4a: red-dragon full-suite gate + push + submodule bump

**Files:** none new — validation + cross-repo wiring.

- [ ] **Step 1: Build the bridge JAR (required for the full suite)**

Run: `cd ~/code/red-dragon && make jar`
Expected: JAR built (or up to date).

- [ ] **Step 2: Run the full red-dragon suite**

Run: `cd ~/code/red-dragon && make test`
Expected: same pass/fail counts as before this plan started (record the pre-plan baseline first if not already known: `git stash` is NOT needed — compare against the last known-green count on `main`). Zero new failures.

- [ ] **Step 3: Run lint**

Run: `cd ~/code/red-dragon && make lint`
Expected: all import-linter contracts kept.

- [ ] **Step 4: Push red-dragon (ask first per conservative profile)**

```bash
cd ~/code/red-dragon
git log --oneline -4      # show the 4 refactor commits
git push
```

Record the new HEAD SHA.

- [ ] **Step 5: Bump the `vendor/red-dragon` submodule in red-dragon-forge**

```bash
cd ~/code/red-dragon-forge/vendor/red-dragon
git fetch && git checkout <new-red-dragon-SHA>
cd ~/code/red-dragon-forge
git add vendor/red-dragon
git commit -m "chore: bump vendor/red-dragon to graph-analysis-core leaf refactor"
```

Do NOT push forge yet — Task 7 bundles the forge-side verification.

---

## Task 5: Extract CSD parsing from `dispatcher.py` into `cics/csd_parse.py`

**Files:**
- Create: `red-dragon-forge/cicada/cics/csd_parse.py`
- Modify: `red-dragon-forge/cicada/cics/dispatcher.py`
- Test: `red-dragon-forge/cicada/tests/unit/cics/test_dispatcher.py` (`test_parse_csd`, `test_parse_csd_files*`)

**Interfaces:**
- Produces: `cics.csd_parse.parse_csd(csd_path: Path) -> dict[str, str]` and `cics.csd_parse.parse_csd_files(csd_path: Path) -> dict[str, str]`, re-exported from `cics.dispatcher` so `from cics.dispatcher import parse_csd, parse_csd_files` still resolves (used by `bootstrap.py`, `test_dispatcher.py`, and — until Task 6 — `flow_map.py`). Consumed by Task 6.

- [ ] **Step 1: Baseline the CSD tests**

Run: `cd ~/code/red-dragon-forge/cicada && uv run --no-sync python -m pytest tests/unit/cics/test_dispatcher.py -q`
Expected: PASS (record count). CSD parsing is pure Lark — no JAR needed for these specific tests, but the file may import VM symbols; if collection fails for lack of JAR, run just the CSD tests: `... test_dispatcher.py -k "parse_csd" -q`.

- [ ] **Step 2: Create the leaf module**

Create `red-dragon-forge/cicada/cics/csd_parse.py` with the CSD grammar, `_CsdTransformer`, `parse_csd`, `parse_csd_files` **moved verbatim** from `dispatcher.py` (current lines 325–389), plus the `logging`/`Lark` imports and module logger they use:

```python
"""CSD parsing — parse_csd (transid -> program) and parse_csd_files
(logical file -> physical DSNAME) plus their Lark grammar/transformer.

Extracted from cics.dispatcher: the CSD parser is a self-contained text/Lark
side-utility of that VM-dispatcher file, sharing nothing with run_cics /
CicsRegion. Lifting it here lets static-analysis consumers (the knowledge-graph
CICS flow builder) use CSD parsing without importing the VM. cics.dispatcher
re-exports both functions for backward compatibility.
"""

from __future__ import annotations

import logging
from pathlib import Path

from lark import Lark, Transformer

logger = logging.getLogger(__name__)
```

Then paste `_CSD_GRAMMAR`, `_csd_parser = Lark(...)`, `_CsdTransformer`, `parse_csd`, `parse_csd_files` **exactly** as they are in `dispatcher.py` lines 325–389. (Cross-check against `experiments/standalone-graph/port/cics/csd_parse.py`, which is this same extraction — the grammar and both functions must match it byte-for-byte.)

- [ ] **Step 3: Replace the CSD block in `dispatcher.py` with a re-export**

In `red-dragon-forge/cicada/cics/dispatcher.py`, delete lines 325–389 (the `_CSD_GRAMMAR` through `parse_csd_files` block) and add a re-export near the top imports:

```python
from cics.csd_parse import parse_csd as parse_csd, parse_csd_files as parse_csd_files
```

Remove the now-unused `Lark`/`Transformer` imports from `dispatcher.py` **only if** nothing else in the file uses them (grep first: `grep -n 'Lark\|Transformer' cics/dispatcher.py`). Keep everything else (the VM dispatcher) untouched.

- [ ] **Step 4: Sanity-check the re-export**

Run: `cd ~/code/red-dragon-forge/cicada && uv run --no-sync python -c "from cics.dispatcher import parse_csd, parse_csd_files; from cics.csd_parse import parse_csd as p; assert parse_csd is p; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Run the CSD + dispatcher tests and import-linter**

Run: `cd ~/code/red-dragon-forge/cicada && uv run --no-sync python -m pytest tests/unit/cics/test_dispatcher.py -q && uv run --no-sync lint-imports --config ../.importlinter`
Expected: PASS, same count as Step 1; contracts kept (`builtins-no-dispatcher` unaffected — `csd_parse` is a new sibling, not `dispatcher`).

- [ ] **Step 6: Commit**

```bash
cd ~/code/red-dragon-forge/cicada
git add cics/csd_parse.py cics/dispatcher.py
git commit -m "refactor: extract CSD parsing from dispatcher into cics.csd_parse leaf"
```

---

## Task 6: Split `flow_map.py` into `flow_graph_core` (verbs-as-data) + `verb_source_lowering`

**Files:**
- Create: `red-dragon-forge/cicada/cics/flow_graph_core.py`
- Create: `red-dragon-forge/cicada/cics/verb_source_lowering.py`
- Modify: `red-dragon-forge/cicada/cics/flow_map.py`
- Test: `red-dragon-forge/cicada/tests/integration/cics/test_flow_graph.py`, `tests/integration/cics/test_flow_map.py`

**Interfaces:**
- Consumes: `cics.csd_parse.parse_csd`/`parse_csd_files` (Task 5); `cics.flow_observer.CicsVerb`/`field_direction`; `interpreter.project.graph_types`.
- Produces:
  - `cics.flow_graph_core.build_flow_map(transid_to_program: dict[str, str], verbs_by_program: dict[str, list[CicsVerb]], bms_mapsets: dict[str, BmsMapSet]) -> list[dict]`
  - `cics.flow_graph_core.build_flow_graph(transid_to_program: dict[str, str], verbs_by_program: dict[str, list[CicsVerb]], bms_mapsets: dict[str, BmsMapSet], file_to_dataset: dict[str, str]) -> tuple[list[GraphNode], list[GraphEdge]]`
  - `cics.verb_source_lowering.compile_all_programs(csd_source: str, cobol_sources: dict[str, bytes], parser) -> tuple[dict[str, str], dict[str, list[CicsVerb]]]` (the lowering-based driver — `_CollectingObserver` + compile loop).
  - `cics.flow_map.extract_transaction_flow_map(...)` and `extract_transaction_flow_graph(...)` keep **identical** signatures; they now compose the driver + core.

- [ ] **Step 1: Baseline the flow tests**

Run: `cd ~/code/red-dragon-forge/cicada && make jar hlasm && uv run --no-sync python -m pytest tests/integration/cics/test_flow_graph.py tests/integration/cics/test_flow_map.py -q`
Expected: PASS (record counts). These are the behavior-preservation gate for the split.

- [ ] **Step 2: Create `flow_graph_core.py` — the verbs-as-data builder leaf**

Create `red-dragon-forge/cicada/cics/flow_graph_core.py`. Move **verbatim** from `flow_map.py`: `_bms_fields` (lines 86–98), `_enrich_verb` (101–111), `_VSAM_FILE_EDGE_KIND` (149–158), `_verb_edge` (161–209). Add two public builders that are the **byte-identical bodies** of today's `extract_transaction_flow_map` (loop at lines 136–146) and `extract_transaction_flow_graph` (node/edge build at lines 244–285), but taking already-sourced data instead of doing CSD parsing / compilation:

```python
"""CICS flow-graph building — verbs-as-data core shared by production and the
knowledge-graph pipeline.

Given a transid→program map and per-program CicsVerb lists (however sourced —
production lowers each program; the graph pipeline walks the typed ASG), build
either the JSON transaction flow map or the CICS-flow portion of the shared
knowledge graph. This module does NO CSD parsing, NO compilation, and imports
NO lowering machinery — it is the leaf the graph pipeline copies. See
cics.verb_source_lowering for production's verb source and cics.flow_map for the
composed public entry points.
"""

from __future__ import annotations

from typing import Any

from bms_copybook_gen.models import BmsMapSet
from cics.flow_observer import CicsVerb, field_direction
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def _bms_fields(verb: CicsVerb, bms_mapsets: dict[str, BmsMapSet]) -> list[dict]:  # type: ignore[type-arg]
    # ...verbatim from flow_map.py lines 86–98...


def _enrich_verb(verb: CicsVerb, bms_mapsets: dict[str, BmsMapSet]) -> dict:  # type: ignore[type-arg]
    # ...verbatim from flow_map.py lines 101–111...


def build_flow_map(
    transid_to_program: dict[str, str],
    verbs_by_program: dict[str, list[CicsVerb]],
    bms_mapsets: dict[str, BmsMapSet],
) -> list[dict]:  # type: ignore[type-arg]
    """Build the JSON transaction flow map from already-sourced verbs."""
    results: list[dict] = []  # type: ignore[type-arg]
    for transid, prog_name in transid_to_program.items():
        verbs = verbs_by_program.get(prog_name, [])
        results.append(
            {
                "transid": transid,
                "entry_program": prog_name,
                "flow": [_enrich_verb(v, bms_mapsets) for v in verbs],
            }
        )
    return results


_VSAM_FILE_EDGE_KIND: dict[str, EdgeKind] = {
    # ...verbatim from flow_map.py lines 149–158...
}


def _verb_edge(verb: CicsVerb, bms_mapsets: dict[str, BmsMapSet]) -> GraphEdge | None:
    # ...verbatim from flow_map.py lines 161–209...


def build_flow_graph(
    transid_to_program: dict[str, str],
    verbs_by_program: dict[str, list[CicsVerb]],
    bms_mapsets: dict[str, BmsMapSet],
    file_to_dataset: dict[str, str],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Build the CICS-flow graph portion from already-sourced verbs + CSD file
    edges. Every node id is uppercased (the standard CICS/COBOL convention)."""
    nodes: dict[tuple[NodeKind, str], GraphNode] = {}
    edges: list[GraphEdge] = []

    def _add_node(kind: NodeKind, node_id: str) -> str:
        nodes.setdefault((kind, node_id), GraphNode(id=node_id, kind=kind))
        return node_id

    for transid, prog_name in transid_to_program.items():
        transid_id = _add_node(NodeKind.TRANSACTION, transid.upper())
        prog_id = _add_node(NodeKind.PROGRAM, prog_name.upper())
        edges.append(
            GraphEdge(
                source=transid_id,
                source_kind=NodeKind.TRANSACTION,
                target=prog_id,
                target_kind=NodeKind.PROGRAM,
                kind=EdgeKind.STARTS,
            )
        )

        for verb in verbs_by_program.get(prog_name, []):
            edge = _verb_edge(verb, bms_mapsets)
            if edge is None:
                continue
            _add_node(edge.source_kind, edge.source)
            _add_node(edge.target_kind, edge.target)
            edges.append(edge)

    for file_name, dataset_name in file_to_dataset.items():
        file_id = _add_node(NodeKind.CICS_FILE, file_name)
        dataset_id = _add_node(NodeKind.DATASET, dataset_name)
        edges.append(
            GraphEdge(
                source=file_id,
                source_kind=NodeKind.CICS_FILE,
                target=dataset_id,
                target_kind=NodeKind.DATASET,
                kind=EdgeKind.DEFINES_DATASET,
            )
        )

    return list(nodes.values()), edges
```

Fill each `# ...verbatim...` marker with the exact lines cited. The `_add_node`/loop bodies above are copied unchanged from lines 244–285.

- [ ] **Step 3: Create `verb_source_lowering.py` — the production verb-source driver**

Create `red-dragon-forge/cicada/cics/verb_source_lowering.py` with `_CollectingObserver` (verbatim from `flow_map.py` lines 22–41) and a `compile_all_programs` that is today's `_compile_all_programs` body (lines 44–83) with `parse_csd` imported from the new `csd_parse` leaf:

```python
"""Production verb source for CICS flow analysis: lower each program through the
CICS lowering strategy and collect CicsVerb events off a CollectingObserver.

This is the driver behind cics.flow_map's public entry points. The knowledge-
graph pipeline does NOT use this module — it sources the same
{program: [CicsVerb]} shape from a typed-ASG walk instead — which is why the
lowering imports live here, isolated from the shared cics.flow_graph_core.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from cics.flow_observer import CicsVerb


class _CollectingObserver:
    """Accumulates CicsVerb events for one program compilation, tagging program name."""

    def __init__(self, program_name: str) -> None:
        self._program_name = program_name
        self.verbs: list[CicsVerb] = []

    def on_verb(self, verb: CicsVerb) -> None:
        # Strategy leaves verb.program = ""; tag it here with the known program name.
        self.verbs.append(
            CicsVerb(
                verb=verb.verb,
                program=self._program_name,
                map_name=verb.map_name,
                mapset_name=verb.mapset_name,
                xctl_target=verb.xctl_target,
                transid=verb.transid,
                file_name=verb.file_name,
            )
        )


def compile_all_programs(
    csd_source: str,
    cobol_sources: dict[str, bytes],
    parser: Any,
) -> tuple[dict[str, str], dict[str, list[CicsVerb]]]:
    """Parse the CSD and compile each distinct referenced program once, via the
    CICS lowering strategy. Returns (transid_to_program, {program: [CicsVerb]})."""
    from cics.csd_parse import parse_csd  # noqa: PLC0415
    from cics.bootstrap import compile_cics_program  # noqa: PLC0415
    from cics.coprocessor import build_cics_spec  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csd", delete=False) as f:
        f.write(csd_source)
        csd_path = Path(f.name)
    transid_to_program = parse_csd(csd_path)
    csd_path.unlink(missing_ok=True)

    compiled_verbs: dict[str, list[CicsVerb]] = {}
    for prog_name in transid_to_program.values():
        if prog_name in compiled_verbs:
            continue
        raw = cobol_sources.get(prog_name)
        if raw is None:
            compiled_verbs[prog_name] = []
            continue
        observer = _CollectingObserver(prog_name)
        spec = build_cics_spec(
            context_holder=[None],
            result_holder=[None],
            observer=observer,
        )
        compile_cics_program(raw, parser, spec)
        compiled_verbs[prog_name] = observer.verbs

    return transid_to_program, compiled_verbs
```

- [ ] **Step 4: Rewrite `flow_map.py` as the thin composition**

Replace `red-dragon-forge/cicada/cics/flow_map.py` so it keeps ONLY the two public entry points, composing the driver + CSD file parse + core. Delete `_CollectingObserver`, `_compile_all_programs`, `_bms_fields`, `_enrich_verb`, `_VSAM_FILE_EDGE_KIND`, `_verb_edge` (all now in the two new modules):

```python
"""extract_transaction_flow_map() / extract_transaction_flow_graph() — static
analysis builder APIs (public, unchanged signatures).

Thin composition over: cics.verb_source_lowering (lowers each program to
CicsVerb events), cics.csd_parse (CSD file→dataset edges), and
cics.flow_graph_core (verbs-as-data graph/map building). The verb-sourcing and
graph-building phases are separated so the knowledge-graph pipeline can reuse
flow_graph_core with its own (lowering-free) verb source.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from bms_copybook_gen.models import BmsMapSet
from cics.csd_parse import parse_csd_files
from cics.flow_graph_core import build_flow_graph, build_flow_map
from cics.verb_source_lowering import compile_all_programs
from interpreter.project.graph_types import GraphEdge, GraphNode


def extract_transaction_flow_map(
    csd_source: str,
    bms_mapsets: dict[str, BmsMapSet],
    cobol_sources: dict[str, bytes],
    *,
    parser: Any = None,
) -> list[dict]:  # type: ignore[type-arg]
    """Static analysis: extract a JSON transaction flow map from a CICS project.

    Args:
        csd_source: CSD text with DEFINE TRANSACTION(...) PROGRAM(...) entries.
        bms_mapsets: parsed BmsMapSet models keyed by mapset name.
        cobol_sources: program name → raw (un-prepassed) COBOL bytes.
        parser: ProLeap parser instance.

    Returns:
        List of dicts, one per transaction, in CSD order.
    """
    transid_to_program, verbs_by_program = compile_all_programs(
        csd_source, cobol_sources, parser
    )
    return build_flow_map(transid_to_program, verbs_by_program, bms_mapsets)


def extract_transaction_flow_graph(
    csd_source: str,
    bms_mapsets: dict[str, BmsMapSet],
    cobol_sources: dict[str, bytes],
    *,
    parser: Any = None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Static analysis: extract the CICS-flow portion of the shared knowledge
    graph (TRANSACTION/PROGRAM/BMS_MAP nodes; STARTS/XCTL/LINK/RETURN_TRANSID/
    SENDS_MAP/RECEIVES_MAP edges), plus CICS_FILE -> DATASET edges from the CSD's
    own DEFINE FILE(...) DSNAME(...) entries.

    Same inputs and compilation as extract_transaction_flow_map — a different
    output shape, not new extraction.
    """
    transid_to_program, verbs_by_program = compile_all_programs(
        csd_source, cobol_sources, parser
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csd", delete=False) as f:
        f.write(csd_source)
        csd_path = Path(f.name)
    file_to_dataset = parse_csd_files(csd_path)
    csd_path.unlink(missing_ok=True)

    return build_flow_graph(
        transid_to_program, verbs_by_program, bms_mapsets, file_to_dataset
    )
```

- [ ] **Step 5: Run the flow tests (behavior-preservation gate)**

Run: `cd ~/code/red-dragon-forge/cicada && uv run --no-sync python -m pytest tests/integration/cics/test_flow_graph.py tests/integration/cics/test_flow_map.py -q`
Expected: PASS, **identical** counts to Step 1.

- [ ] **Step 6: Run import-linter**

Run: `cd ~/code/red-dragon-forge/cicada && uv run --no-sync lint-imports --config ../.importlinter`
Expected: contracts kept. (`verb_source_lowering` imports `cics.bootstrap`/`cics.coprocessor` lazily inside the function, as `_compile_all_programs` did — the same edges as before, just relocated.)

- [ ] **Step 7: Commit**

```bash
cd ~/code/red-dragon-forge/cicada
git add cics/flow_graph_core.py cics/verb_source_lowering.py cics/flow_map.py
git commit -m "refactor: split flow_map into flow_graph_core (verbs-as-data) + verb_source_lowering"
```

---

## Task 6a: cicada full-suite gate + push

**Files:** none new — validation.

- [ ] **Step 1: Run the full cicada suite**

Run: `cd ~/code/red-dragon-forge/cicada && make test`
Expected: same pass/fail counts as the pre-plan baseline; zero new failures.

- [ ] **Step 2: Run lint**

Run: `cd ~/code/red-dragon-forge/cicada && make lint`
Expected: contracts kept.

- [ ] **Step 3: Push cicada (ask first per conservative profile)**

```bash
cd ~/code/red-dragon-forge/cicada
git log --oneline -2
git push
```

---

## Task 7: Forge-side verification — bump, experiment re-port, fitness gate

**Files:**
- Modify: `red-dragon-forge/experiments/standalone-graph/port/**` (copy the new leaves byte-for-byte; drop the surgical deletions)
- Modify: `red-dragon-forge/experiments/standalone-graph/port/generate_diff_report.py` (repoint PAIRS to the new leaf modules)

**Interfaces:** none — this proves the seam landed where the port's deletions were. It is the overall fitness gate.

- [ ] **Step 1: Ensure the submodule bump from Task 4a is in place**

Run: `cd ~/code/red-dragon-forge && git submodule status vendor/red-dragon`
Expected: the new red-dragon SHA (matching Task 4a Step 4).

- [ ] **Step 2: Re-point the experiment port to copy the new leaf modules**

The port currently copies fat files it then had to delete from. Replace those port copies with byte-for-byte copies of the new leaves, and give the port its own lowering-free verb-source driver instead of the `flow_map.py` seam-swap:
- `port/cics/csd_parse.py` — already the extraction target; confirm it matches `cicada/cics/csd_parse.py` byte-for-byte (`diff`).
- `port/cics/flow_graph_core.py` — NEW: copy `cicada/cics/flow_graph_core.py` byte-for-byte, rewriting only the three `import` lines to the `port.*` namespace (`port.cics.flow_observer`, `port.interpreter.project.graph_types`) and aliasing `BmsMapSet = Any` as the existing port `flow_map.py` did (the port parses no BMS).
- `port/cics/flow_source_asg.py` — NEW: the port's ASG-walk verb source (`_program_verbs`/`_exec_cics_statements`/`_find_operand`/`_resolve`/`_field_value` — lift from the current `port/cics/flow_map.py` lines 54–207) exposing `compile_all_programs(csd_source, cobol_sources, parser)` with the same `(transid_to_program, verbs_by_program)` return.
- `port/cics/flow_map.py` — reduce to the same thin composition as production `flow_map.py`, but importing `compile_all_programs` from `port.cics.flow_source_asg` and `parse_csd_files` from `port.cics.csd_parse`. This makes the port's flow layer a byte-for-byte core copy + a small local driver, eliminating the in-file lowering-seam excision.
- `port/interpreter/project/cobol_imports.py` — NEW: copy `interpreter/project/cobol_imports.py` byte-for-byte, rewiring the `import_types` import to the `port.*` namespace; update `port/interpreter/project/imports.py` (or its consumer `port/jackal/cobol_file_graph.py`) to call `extract_cobol_imports` from this leaf.
- Confirm `port/interpreter/language.py` and `port/interpreter/project/import_types.py` copy the new red-dragon leaves byte-for-byte (rewiring nothing but namespace where needed).

- [ ] **Step 3: Update the diff-report PAIRS**

In `port/generate_diff_report.py`, update `PAIRS` so each new port leaf maps to its production source (e.g. `cicada/cics/flow_graph_core.py` → `port/cics/flow_graph_core.py`; `vendor/red-dragon/interpreter/project/cobol_imports.py` → `port/interpreter/project/cobol_imports.py`; `vendor/red-dragon/interpreter/language.py`, `.../import_types.py`). The leaf copies should now show **+0/-0 (byte-identical)** except namespace-rewire lines.

- [ ] **Step 4: Regenerate the diff report and confirm the leaves are byte-identical**

Run: `cd ~/code/red-dragon-forge && uv run --no-sync python experiments/standalone-graph/port/generate_diff_report.py`
Expected: `flow_graph_core.py`, `csd_parse.py` show byte-identical (0/0) or namespace-only diffs; the previous large seam-swap diff on `flow_map.py` is gone (now a thin composition matching production).

- [ ] **Step 5: Run the experiment fitness harness**

Run the standalone-graph build + `compare.py` with the bridge JAR env vars (as in `experiments/standalone-graph/oracle/generate_reference.py`'s header):
```bash
cd ~/code/red-dragon-forge
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
uv run --no-sync python experiments/standalone-graph/compare.py
```
Expected: **449 nodes / 803 edges**, empty diff against the reference.

- [ ] **Step 6: Run the forge aggregate knowledge-graph test**

Run: `cd ~/code/red-dragon-forge && uv run --no-sync python -m pytest tests/integration/test_knowledge_graph_carddemo.py -q`
Expected: PASS (the production pipeline, now importing the bumped red-dragon leaves + refactored cicada, still builds 449/803).

- [ ] **Step 7: Commit the forge changes (ask first per conservative profile)**

```bash
cd ~/code/red-dragon-forge
git add vendor/red-dragon experiments/standalone-graph
git commit -m "chore: bump red-dragon + re-port experiment onto graph-analysis-core leaves"
```

(Update `.talismanrc` by-checksum entries if the pre-commit Talisman hook flags any changed file, per repo convention.)

---

## Self-Review

**Spec coverage:**
- imports.py → cobol_imports (Task 4) ✅; dispatcher → csd_parse (Task 5) ✅; types → import_types (Task 3) ✅; constants → language (Task 2) ✅; frontend_extension split (Task 1) ✅; flow_map verbs-as-data split (Task 6) ✅.
- Behavior preservation: per-repo full suites (Tasks 4a, 6a) + experiment byte-for-byte + 449/803 (Task 7) ✅.
- Cross-repo execution ordered by blast radius, pins bumped (Tasks 4a, 5–6, 7) ✅.
- Permanent re-export shims, no import-site migration ✅ (Global Constraints + every re-export step keeps existing paths resolving).
- import-linter `cobol-isolation` repoint (the one contract edit) ✅ (Task 1 Step 5).

**Type consistency:** `extract_cobol_imports(source: bytes, source_file: Path) -> list[ImportRef]` (Task 4) matches its call site in `imports.py`. `compile_all_programs(csd_source, cobol_sources, parser) -> (dict[str,str], dict[str,list[CicsVerb]])` (Task 6, `verb_source_lowering`) matches `build_flow_map`/`build_flow_graph` inputs (Task 6, `flow_graph_core`). `parse_csd`/`parse_csd_files(csd_path: Path) -> dict[str,str]` (Task 5) matches both re-export consumers and Task 6's `parse_csd_files` call.

**Placeholder scan:** the only `# ...verbatim from lines X–Y...` markers are in Task 6 Step 2, each with exact source line ranges to copy — the code exists verbatim in `flow_map.py` and must be lifted unchanged (reproducing ~120 identical lines here would violate DRY against the source of truth). All genuinely-new code (re-export lines, new builders, drivers, thin composition) is shown in full.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-09-graph-analysis-core-decoupling.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration. Note: tasks span three repos and require the red-dragon push + submodule bump (Task 4a) before Task 7; the controller must gate that cross-repo step on the conservative git profile.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
