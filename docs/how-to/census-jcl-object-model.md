# Census the JCL object model on a corpus

Instructions for an agent on a machine that holds a production-scale JCL corpus. The run
measures how much of the corpus jackal's JCL object model (units 1–4 of
[the build spec](../superpowers/specs/2026-10-10-jackal-jcl-object-model-build-design.md))
parses and expands, and which JCL constructs it meets. It is unit 5 of that spec, issue
`red-dragon-forge-yv3`.

## Confidentiality: read this first

The corpus belongs to a client. **Nothing that identifies the client or names anything in
the corpus may leave the machine**, in any form: not in the results, not in messages, issues,
commits, file names, test names or summaries.

Never include, quote or paraphrase:

- job, step, PROC, program, DD or dataset names, symbolic parameter names or values;
- organisation, application, team, system or product names, user IDs, accounting fields,
  programmer-name fields, mail addresses, host or node names;
- file or directory paths of the corpus;
- any text from a member: statements, comments, in-stream data, error messages that quote
  input;
- counts or details that single out one member (say "one member", never which).

What may leave: the two files the script writes (`summary.json`, `report.md`), and synthetic
reproductions written with invented names (step 4). The script reduces every error to a fixed
category and every construct to a count, then scans its own output for each identifier it
read from the corpus and **refuses to write** if one appears. Do not weaken or bypass that
check; if it refuses, report only that it refused.

Keep every working file (output, scratch copies of members) **outside the repository**, for
example under `~/jcl-census-<date>/`. Do not commit anything from this run.

## 1. Prepare

```bash
cd <red-dragon-forge clone>
git checkout main && git pull           # needs the coordinate-model commit or later
make setup                              # builds both bridge JARs and syncs Python
. ./bridge-env.sh
```

Note where the corpus keeps its JCL members and its PROC libraries. Members may have no
file extension (copied PDS members); PROCs may too. The script handles both.

## 2. Save the script

Save the script below as `~/jcl-census-<date>/census_jcl.py`, outside the repository.

```python
"""Census of jackal's JCL object model over a corpus: counts and error categories only.

Writes summary.json and report.md to --out. Neither file may contain a name or any text
from the corpus: errors are reduced to fixed categories, constructs to counts, and a final
scan fails the run if any identifier seen in the corpus appears in either file.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from jackal.expansion import DirectoryProcLibrary, ExpandedJob, expand_procs
from jackal.jcl.bridge_parser import JclParseError
from jackal.jcl.parser import bridge_parser
from jackal.model import (
    AllPriorSteps,
    Always,
    BackwardRef,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    ResolvedDd,
    ResolvedProgramStep,
    SetStatement,
    TempRef,
    UnexpandedCall,
    CalledProcScope,
    IfBlock,
    Job,
    NotOverridden,
    ProcCall,
    ProgramStep,
    StepRef,
)
from jackal.value_parts import Symbol

# Phrases the bridge and the deserializer use; a message is reduced to the first that occurs.
_KNOWN_ERRORS = (
    "mismatched input",
    "no viable alternative",
    "extraneous input",
    "token recognition error",
    "missing",
    "IF without ENDIF",
    "ELSE without IF",
    "ENDIF without IF",
    "unbalanced IF expression",
    "IF expression missing a closing parenthesis",
    "IF expression expected a term",
    "COND test is not",
    "step reference with more than two names",
    "ABENDCC value is neither",
    "expected TRUE or FALSE",
    "take = or NE only",
    "malformed/incomplete JSON",
)
_JAVA_EXCEPTION = re.compile(r"\b(?:java|org|com)\.[\w.]*?(\w+(?:Exception|Error))\b")
_WORD = re.compile(r"[A-Z0-9@#$][A-Z0-9@#$-]{3,}")
_GENERIC = frozenset(
    "NORMAL EVEN ONLY TRUE FALSE NONE PASS KEEP DELETE CATLG UNCATLG SHR OLD NEW MOD "
    "JCLERROR DANGLINGREFERENCE DANGLINGDDREFERENCE FORWARDREFERENCE REFERENCETOPROCCALL "
    "OVERRIDENAMESNOSTEP CIRCULARPROC".split()
)


def _category(message: str) -> str:
    java = _JAVA_EXCEPTION.search(message)
    if java:
        return f"bridge crash: {java.group(1)}"
    return next(
        (f"bridge: {p}" for p in _KNOWN_ERRORS if p in message), "bridge: other"
    )


@dataclass
class Tally:
    lock: threading.Lock = field(default_factory=threading.Lock)
    counts: Counter[str] = field(default_factory=Counter)
    parse_seconds: list[float] = field(default_factory=list)
    expand_seconds: list[float] = field(default_factory=list)
    identifiers: set[str] = field(default_factory=set)

    def add(self, counts: Counter[str], parse: float, expand: float, ids: set[str]) -> None:
        with self.lock:
            self.counts.update(counts)
            self.parse_seconds.append(parse)
            if expand >= 0:
                self.expand_seconds.append(expand)
            self.identifiers.update(ids)


class _WarningCounter(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.count = 0
        self.lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        with self.lock:
            self.count += 1


def _statements(statements: Iterable[object], depth: int = 0) -> Iterable[tuple[object, int]]:
    for s in statements:
        yield s, depth
        if isinstance(s, IfBlock):
            yield from _statements((*s.then, *s.otherwise), depth + 1)


def _ref_kind(target: object) -> str:
    if isinstance(target, StepRef):
        return "called-proc" if isinstance(target.scope, CalledProcScope) else "own-scope"
    return "all-prior"


def _dsn_kind(dsn: object) -> str:
    kinds = {
        DirectDSN: "dataset",
        TempRef: "temp",
        BackwardRef: "referback",
        InStreamDSN: "in-stream",
        DummyDSN: "dummy",
        NoDSN: "none",
    }
    return kinds[type(dsn)]


def _dd_counts(c: Counter[str], dds: Iterable[object], ids: set[str], where: str) -> None:
    for dd in dds:
        ids.add(dd.ddname.text.upper())
        c[f"{where} DD"] += 1
        c[f"{where} DD dsn: {_dsn_kind(dd.dsn)}"] += 1
        if isinstance(dd.dsn, BackwardRef):
            c[f"{where} DD referback scope: {_ref_kind(dd.dsn.step)}"] += 1
        if isinstance(dd.dsn, DirectDSN):
            if any(isinstance(p, Symbol) for p in dd.dsn.name):
                c[f"{where} DD dataset name with a symbol"] += 1
            for p in dd.dsn.name:
                text = p.text if not isinstance(p, Symbol) else p.name.text
                ids.update(q.upper() for q in re.split(r"[.()&]", text) if q)
        if dd.concatenated:
            c[f"{where} DD concatenated"] += 1
            c[f"{where} concatenation members"] += len(dd.concatenated)
        if dd.sysout:
            c[f"{where} DD sysout"] += 1
        d = dd.disposition()
        c[f"{where} DISP {d.status.value},{d.normal.value},{d.abnormal.value}"] += 1


def _cond_counts(c: Counter[str], cond: object, where: str) -> None:
    if cond.bypass_tests:
        c[f"{where} steps with COND tests"] += 1
        c[f"{where} COND tests"] += len(cond.bypass_tests)
    for t in cond.bypass_tests:
        c[f"{where} COND test target: {_ref_kind(t.target)}"] += 1
    if cond.abend_mode.value != "NORMAL":
        c[f"{where} COND {cond.abend_mode.value}"] += 1


def _parsed_counts(job: Job, ids: set[str]) -> Counter[str]:
    c: Counter[str] = Counter()
    ids.add(job.name.upper())
    c["parsed: JOB COND tests"] += len(job.end_job_tests)
    depths = [depth for _, depth in _statements(job.steps)]
    c[f"parsed: members whose deepest IF nesting is {max(depths, default=0)}"] += 1
    for s, depth in _statements(job.steps):
        if depth:
            c["parsed: statements inside an IF"] += 1
        if isinstance(s, IfBlock):
            c["parsed: IF blocks"] += 1
            if s.otherwise:
                c["parsed: IF blocks with ELSE"] += 1
            continue
        if isinstance(s, SetStatement):
            c["parsed: SET statements"] += 1
            ids.update(name.text.upper() for name, _ in s.assignments)
            continue
        ids.add(s.label.rendered().upper())
        if isinstance(s, ProgramStep):
            ids.add(s.pgm.name.upper())
            c["parsed: program steps"] += 1
            _cond_counts(c, s.cond, "parsed:")
            _dd_counts(c, s.dds, ids, "parsed:")
            continue
        ids.add(s.proc.name.upper())
        ids.update(name.text.upper() for name, _ in s.symbol_overrides)
        c["parsed: PROC calls"] += 1
        c["parsed: PROC symbol overrides"] += len(s.symbol_overrides)
        if not isinstance(s.cond_for_every_step, NotOverridden):
            c["parsed: PROC call COND= (every step)"] += 1
        if not isinstance(s.parm_for_first_step, NotOverridden):
            c["parsed: PROC call PARM= (first step)"] += 1
        c["parsed: PROC call per-step override groups"] += len(s.per_step)
        _dd_counts(c, s.dds_for_first_step, ids, "parsed: override")
        for _, o in s.per_step:
            _dd_counts(c, o.dds, ids, "parsed: override")
    return c


def _expanded_counts(job: ExpandedJob) -> Counter[str]:
    c: Counter[str] = Counter()
    for q in job.steps:
        c["expanded: steps"] += 1
        c[f"expanded: steps at PROC depth {len(q.coordinates)}"] += 1
        if isinstance(q, UnexpandedCall):
            c["expanded: unexpanded PROC calls (PROC in no library)"] += 1
            continue
        for t in q.step.cond.bypass_tests:
            if not isinstance(t.target, AllPriorSteps) and not isinstance(t.target.target, ResolvedProgramStep):
                c["expanded: COND tests naming an unresolved step"] += 1
        for dd in q.step.dds:
            if isinstance(dd.dsn, BackwardRef) and not isinstance(dd.dsn.dd, ResolvedDd):
                c["expanded: referbacks naming an unresolved step or DD"] += 1
        if q.step.guard != Always():
            c["expanded: steps under an IF (runner refuses)"] += 1
        _cond_counts(c, q.step.cond, "expanded:")
        for dd in q.step.dds:
            if isinstance(dd.dsn, DirectDSN) and any(isinstance(p, Symbol) for p in dd.dsn.name):
                c["expanded: DD dataset name still holding a symbol"] += 1
    return c


def census_member(path: Path, library: DirectoryProcLibrary, tally: Tally) -> None:
    ids: set[str] = set()
    c: Counter[str] = Counter({"members": 1})
    started = time.perf_counter()
    try:
        job = bridge_parser().parse(path.read_text(errors="replace"))
    except JclParseError as error:
        c["members not parsed"] += 1
        c[f"parse failure: {_category(str(error))}"] += 1
        tally.add(c, time.perf_counter() - started, -1, ids)
        return
    parsed_at = time.perf_counter()
    c["members parsed"] += 1
    c.update(_parsed_counts(job, ids))
    try:
        result = expand_procs(job, library)
    except JclParseError as error:
        c["members not expanded"] += 1
        c[f"expansion failure: PROC {_category(str(error))}"] += 1
        tally.add(c, parsed_at - started, time.perf_counter() - parsed_at, ids)
        return
    except (UnicodeDecodeError, OSError) as error:
        c["members not expanded"] += 1
        c[f"expansion failure: {type(error).__name__}"] += 1
        tally.add(c, parsed_at - started, time.perf_counter() - parsed_at, ids)
        return
    if isinstance(result, ExpandedJob):
        c["members expanded"] += 1
        c.update(_expanded_counts(result))
    else:
        c["members not expanded"] += 1
        c[f"expansion failure: {type(result).__name__}"] += 1
    tally.add(c, parsed_at - started, time.perf_counter() - parsed_at, ids)


def _linked_proclib(proclibs: list[Path], out: Path) -> Path:
    links = out / "proclib-links"
    links.mkdir(exist_ok=True)
    for directory in proclibs:
        for member in sorted(p for p in directory.iterdir() if p.is_file()):
            link = links / f"{member.stem.upper()}.prc"
            if not link.exists():
                link.symlink_to(member.resolve())
    return links


def _seconds(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "p50": round(statistics.median(ordered), 3),
        "p90": round(ordered[int(0.9 * (len(ordered) - 1))], 3),
        "max": round(ordered[-1], 3),
    }


def _leaks(texts: Iterable[str], identifiers: set[str]) -> set[str]:
    own_words = set(_WORD.findall(Path(__file__).read_text().upper()))
    corpus = {
        i for i in identifiers if len(i) >= 4 and i not in _GENERIC | own_words
    }
    return {w for t in texts for w in _WORD.findall(t.upper()) if w in corpus}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jcl-dir", type=Path, required=True)
    ap.add_argument("--suffix", default=".jcl", help="case-insensitive; '' for every file")
    ap.add_argument("--proclib", type=Path, action="append", default=[])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    warnings = _WarningCounter()
    logging.getLogger("jackal.expansion").addHandler(warnings)
    library = DirectoryProcLibrary((_linked_proclib(args.proclib, args.out),))
    members = sorted(
        p
        for p in args.jcl_dir.rglob("*")
        if p.is_file() and (not args.suffix or p.suffix.lower() == args.suffix.lower())
    )
    tally = Tally()
    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(lambda p: census_member(p, library, tally), members))
    counts = dict(sorted(tally.counts.items()))
    counts["expanded: warnings (unresolved references and reused names, D6)"] = warnings.count
    summary = {
        "counts": counts,
        "parse_seconds": _seconds(tally.parse_seconds),
        "expand_seconds": _seconds(tally.expand_seconds),
    }
    summary_text = json.dumps(summary, indent=1)
    report = "\n".join(
        ["# JCL object model census", "", "| Measure | Count |", "|---|---|"]
        + [f"| {k} | {v} |" for k, v in counts.items()]
        + ["", f"Parse seconds per member: {summary['parse_seconds']}",
           f"Expansion seconds per member: {summary['expand_seconds']}", ""]
    )
    leaks = _leaks((summary_text, report), tally.identifiers)
    if leaks:
        print(f"REFUSING TO WRITE: {len(leaks)} corpus identifiers in the output", file=sys.stderr)
        return 2
    (args.out / "summary.json").write_text(summary_text)
    (args.out / "report.md").write_text(report)
    print(f"wrote {args.out / 'summary.json'} and {args.out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## 3. Run it

From the repository's `jackal` directory:

```bash
cd <red-dragon-forge clone>/jackal
uv run --no-sync python ~/jcl-census-<date>/census_jcl.py \
  --jcl-dir <corpus JCL directory> \
  --suffix .jcl \
  --proclib <corpus PROC directory> \
  --out ~/jcl-census-<date>/out
```

- `--suffix ''` reads every file under `--jcl-dir` (extensionless members); the match is
  case-insensitive.
- Repeat `--proclib` for each PROC library, in search order. The script links each PROC as
  `NAME.prc` under `--out/proclib-links`, the first library winning.
- `--workers` (default 4) is the number of members parsed at once; each parse starts a JVM.
- Before the full run, try it on about twenty members (a copied subset) to check the setup.

It writes `summary.json` and `report.md` to `--out`.

## 4. Reduce each failure category to a synthetic reproduction

For every `parse failure: …` and `expansion failure: …` row with a non-zero count, and for
`bridge: other` above all, produce a minimal JCL snippet that reproduces the same category:

1. Copy one failing member to a scratch directory outside the repository.
2. Delete statements and parameters while the category stays the same. Re-run the script with
   `--jcl-dir <that scratch dir> --suffix ''` (and the same `--proclib`) to check.
3. When it is minimal, **rewrite every identifier** with invented ones: job `ACCEPT`, steps
   `S1`, `S2`…, PROCs `P1`…, programs `PGMA`…, DDs `IN`, `OUT`, `DD1`…, datasets `T.A`,
   `T.B`…, symbols `HLQ`, `SYM1`…; replace any in-stream data with ` CARD`. Keep the JCL
   syntax that triggers the failure exactly as it was.
4. Re-run on the rewritten snippet and confirm the **same** category. A snippet that no
   longer fails is not a reproduction; go back to step 2.
5. If a failure needs a PROC, rewrite the PROC the same way and pass its directory with
   `--proclib`.

Do the same, with at most three snippets, for any construct row that looks surprising (for
example `expanded: DD dataset name still holding a symbol` far above the parsed count).

## 5. What to return

One message containing:

1. `report.md`, verbatim.
2. `summary.json`, verbatim.
3. The corpus size: member count, and how many PROC libraries were passed. No names.
4. For each failure category: its count and the synthetic snippet from step 4, or "could not
   reduce" with the reason in general terms.
5. Anything that made the run fail or misbehave (a crash, a hang, a refusal by the leak
   check), described without corpus text.

Before sending, check every line once more against the list under *Confidentiality*. When in
doubt, leave it out and say that something was left out.
