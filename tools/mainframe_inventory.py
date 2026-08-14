#!/usr/bin/env python3
"""Inventory the mainframe feature surface a codebase actually uses.

Standalone and stdlib-only by design: it must run against an arbitrary corpus,
including ones this repo's parsers cannot read. Detection is regex-level, so
treat counts as a survey, not a parse.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

_DECK_START = re.compile(r"\bDD\s+(?:\*|DATA)(?=[,\s]|$)")

# JCL operations worth counting as their own statement kind.
_JCL_OPS = frozenset(
    """JOB EXEC DD PROC PEND INCLUDE JCLLIB SET IF ELSE ENDIF THEN OUTPUT
       EXPORT XMIT CNTL ENDCNTL COMMAND NOTIFY""".split()
)

# Keyword parameters. The unglamorous ones (AMP, SMS classes, PATH, SUBSYS,
# RLS, DSNTYPE) are exactly the surface-area tells a shallow scan drops.
_JCL_PARAMS = frozenset(
    """DISP DCB LRECL RECFM BLKSIZE SPACE UNIT VOL VOLUME SYSOUT DUMMY COND
       PARM AMP STORCLAS MGMTCLAS DATACLAS PATH PATHOPTS PATHDISP PATHMODE
       SUBSYS RLS DSNTYPE RECORG KEYLEN KEYOFF LABEL EXPDT RETPD DDNAME DLM
       FREE TIME REGION CLASS MSGCLASS MSGLEVEL NOTIFY TYPRUN RESTART AVGREC
       PROTECT SCHENV ADDRSPC MEMLIMIT ACCT USER GROUP PASSWORD SECMODEL
       BURST CHARS FORMS FCB COPIES DEST HOLD OUTLIM SEGMENT SPIN LIKE
       REFDD SYSAFF PRTY PERFORM RD JOBRC SYMLIST ORDER""".split()
)

_SYSTEM_SYMBOLS = frozenset(
    """SYSUID SYSDATE SYSTIME SYSNAME SYSPLEX SYSCLONE SYSSEQ SYSJOBNAME
       JOBNAME YYMMDD YYYYMMDD LYYMMDD LHHMMSS HHMMSS SYSSMFID SYSR1""".split()
)

_STMT = re.compile(r"^//(\S*)\s+(\S+)")
_JES_CARD = re.compile(r"^/\*(\w+)")
_DD_CONCAT = re.compile(r"^//\s+DD\b")
_DSN = re.compile(r"\bDSN(?:AME)?=([^,\s]+)")
_SYMBOL = re.compile(r"(?<![&A-Z0-9])&([A-Z@#$][A-Z0-9@#$]*)")
_GDG_RELATIVE = re.compile(r"\(\s*[+-]?\d+\s*\)\s*$")
_GDG_ABSOLUTE = re.compile(r"\.G\d{4}V\d{2}\b")
_PDS_MEMBER = re.compile(r"\(([A-Z@#$][A-Z0-9@#$]*)\)\s*$")


def _scan_dsn(value: str, found: Counter[str]) -> None:
    if value.startswith("&&"):
        found["JCL.DSN.TEMP"] += 1
    if value.startswith("*."):
        found["JCL.DSN.REFERBACK"] += 1
    if value.upper() == "NULLFILE":
        found["JCL.DSN.NULLFILE"] += 1
    if _GDG_RELATIVE.search(value):
        found["JCL.DSN.GDG_RELATIVE"] += 1
    elif _PDS_MEMBER.search(value):
        found["JCL.DSN.PDS_MEMBER"] += 1
    if _GDG_ABSOLUTE.search(value):
        found["JCL.DSN.GDG_ABSOLUTE"] += 1


def _scan_jcl(line: str, found: Counter[str]) -> None:
    jes = _JES_CARD.match(line)
    if jes:
        found[f"JCL.JES.{jes.group(1).upper()}"] += 1
        return
    if not line.startswith("//"):
        return

    if _DD_CONCAT.match(line):
        found["JCL.DD.CONCATENATION"] += 1
    stmt = _STMT.match(line)
    if stmt and stmt.group(2).upper() in _JCL_OPS:
        found[f"JCL.STMT.{stmt.group(2).upper()}"] += 1

    for name in _JCL_PARAMS:
        if re.search(rf"\b{name}=", line):
            found[f"JCL.PARM.{name}"] += 1
    disp = re.search(r"\bDISP=\(?([^)\s,]*)(?:,([^)\s,]*))?(?:,([^)\s,]*))?", line)
    if disp:
        for sub in filter(None, disp.groups()):
            found[f"JCL.PARM.DISP.{sub.upper()}"] += 1

    for value in _DSN.findall(line):
        _scan_dsn(value, found)
    for sym in _SYMBOL.findall(line):
        key = (
            f"JCL.SYMBOL.SYSTEM.{sym}" if sym in _SYSTEM_SYMBOLS else "JCL.SYMBOL.USER"
        )
        found[key] += 1


# --------------------------------------------------------------------------
# Tool registry: PGM name -> (deck dialect, control DDs).
#
# The point of the whole script. A step's surface area is decided by which
# foreign tool it invokes and which corner of that tool's control language it
# uses -- and those languages arrive on differently-named DDs (TOOLIN, SYSTSIN,
# SYSLIN, SMPCNTL), so a scanner that only reads SYSIN misses them.
# --------------------------------------------------------------------------


def _phrases(spec: str) -> frozenset[str]:
    """Split a wrapped |-separated literal into whitespace-normalized phrases.

    The tables below wrap across source lines, so a plain split would leave
    newlines embedded in every entry after a break and silently never match.
    """
    return frozenset(" ".join(part.split()) for part in spec.split("|") if part.strip())


_SYSIN = frozenset({"SYSIN"})

_TOOLS: dict[str, tuple[str, frozenset[str]]] = {
    # access method services / no-op
    "IDCAMS": ("idcams", _SYSIN),
    "IEFBR14": ("none", frozenset()),
    # sort family
    "SORT": ("sort", frozenset({"SYSIN", "DFSPARM"})),
    "DFSORT": ("sort", frozenset({"SYSIN", "DFSPARM"})),
    "ICEMAN": ("sort", frozenset({"SYSIN", "DFSPARM"})),
    "SYNCSORT": ("sort", frozenset({"SYSIN", "DFSPARM"})),
    "ICETOOL": ("icetool", frozenset({"TOOLIN"})),
    "SYNCTOOL": ("icetool", frozenset({"TOOLIN"})),
    "ICEGENER": ("iebgener", _SYSIN),
    # IBM data utilities
    "IEBGENER": ("iebgener", _SYSIN),
    "IEBCOPY": ("iebcopy", _SYSIN),
    "IEBUPDTE": ("iebupdte", _SYSIN),
    "IEBPTPCH": ("iebptpch", _SYSIN),
    "IEBCOMPR": ("generic", _SYSIN),
    "IEBEDIT": ("generic", _SYSIN),
    "IEBDG": ("generic", _SYSIN),
    "IEBIMAGE": ("generic", _SYSIN),
    "IEHLIST": ("generic", _SYSIN),
    "IEHPROGM": ("generic", _SYSIN),
    "IEHMOVE": ("generic", _SYSIN),
    "IEHINITT": ("generic", _SYSIN),
    # TSO batch shells (their real content is the SYSTSIN deck)
    "IKJEFT01": ("tso", frozenset({"SYSTSIN"})),
    "IKJEFT1A": ("tso", frozenset({"SYSTSIN"})),
    "IKJEFT1B": ("tso", frozenset({"SYSTSIN"})),
    # Db2
    "DSNUTILB": ("db2util", _SYSIN),
    "DSNTEP2": ("sql", _SYSIN),
    "DSNTEP4": ("sql", _SYSIN),
    "DSNTIAD": ("sql", _SYSIN),
    "DSN1COPY": ("generic", _SYSIN),
    # CICS
    "DFHCSDUP": ("csdup", _SYSIN),
    "DFHSTUP": ("generic", _SYSIN),
    "DFHJUP": ("generic", _SYSIN),
    "DFHMSCAN": ("generic", _SYSIN),
    "SDSF": ("sdsf", frozenset({"ISFIN"})),
    # IMS
    "DFSRRC00": ("none", frozenset()),
    "DFSURGU0": ("generic", _SYSIN),
    "DFSUCUM0": ("generic", _SYSIN),
    # language processors, precompilers/translators, and the binder
    "DSNHPC": ("none", frozenset()),  # Db2 precompiler
    "DFHECP1$": ("none", frozenset()),  # CICS COBOL command translator
    "DFHEAP1$": ("none", frozenset()),  # CICS assembler translator
    "DFHEPP1$": ("none", frozenset()),  # CICS PL/I translator
    "IGYCRCTL": ("none", frozenset()),
    "IGYWCL": ("none", frozenset()),
    "IKFCBL00": ("none", frozenset()),
    "ASMA90": ("none", frozenset()),
    "IEV90": ("none", frozenset()),
    "IEWL": ("binder", frozenset({"SYSLIN"})),
    "HEWL": ("binder", frozenset({"SYSLIN"})),
    "IEWBLINK": ("binder", frozenset({"SYSLIN"})),
    "LINKEDIT": ("binder", frozenset({"SYSLIN"})),
    # storage, transfer, packaging
    "ADRDSSU": ("dssu", _SYSIN),
    "GIMSMP": ("smpe", frozenset({"SMPCNTL"})),
    "FTP": ("ftp", frozenset({"INPUT", "NETRC", "SYSIN"})),
    "DMBATCH": ("dmbatch", frozenset({"SYSIN", "DMPUBLIB"})),
    "PKZIP": ("generic", _SYSIN),
    "AMATERSE": ("generic", _SYSIN),
    "TRSMAIN": ("generic", _SYSIN),
    "BPXBATCH": ("none", frozenset({"STDIN"})),
    # security
    "IRRUT200": ("generic", _SYSIN),
    "IRRDBU00": ("generic", _SYSIN),
    # vendor languages that hide an entire program in a SYSIN deck
    "EZTPA00": ("easytrieve", _SYSIN),
    "SAS": ("sas", _SYSIN),
    "FILEAID": ("generic", _SYSIN),
    "PAN#1": ("generic", _SYSIN),
    "AFOLIBR": ("generic", _SYSIN),
}

# Verbs whose second word changes what the command means.
_TWO_WORD_VERBS: dict[str, frozenset[str]] = {
    "idcams": _phrases("""DEFINE CLUSTER|DEFINE ALTERNATEINDEX|DEFINE AIX|DEFINE PATH|
           DEFINE GENERATIONDATAGROUP|DEFINE GDG|DEFINE NONVSAM|DEFINE SPACE|
           DEFINE USERCATALOG|DEFINE MASTERCATALOG|DEFINE PAGESPACE"""),
    "tso_dsn": _phrases(
        """RUN PROGRAM|BIND PLAN|BIND PACKAGE|REBIND PLAN|REBIND PACKAGE|
           FREE PLAN|FREE PACKAGE"""
    ),
    "csdup": _phrases("""DEFINE TRANSACTION|DEFINE PROGRAM|DEFINE FILE|DEFINE MAPSET|
           DEFINE TRANCLASS|DEFINE TDQUEUE|DEFINE TSMODEL|DEFINE CONNECTION|
           DEFINE SESSIONS|DEFINE TYPETERM|DEFINE GROUP|DEFINE LIST|
           ALTER TRANSACTION|ALTER PROGRAM|ALTER FILE|DELETE GROUP"""),
}

# Bare (parenthesis-free) operands worth counting: each one is real behaviour.
_BARE_OPERANDS: dict[str, frozenset[str]] = {
    "idcams": frozenset(
        """ERASE NOERASE REUSE NOREUSE SPANNED NONSPANNED UPGRADE NOUPGRADE
           UNIQUEKEY NONUNIQUEKEY INDEXED NONINDEXED NUMBERED LINEAR PURGE
           NOPURGE SCRATCH NOSCRATCH RECOVERY SPEED ORDERED UNORDERED
           WRITECHECK IMBED REPLICATE INHIBIT UNIQUE SUBALLOCATION
           REPLACE NOREPLACE VERIFY FORCE""".split()
    ),
    # Bare CICS options that change real behaviour: UPDATE takes a lock,
    # NOHANDLE suppresses condition dispatch, GTEQ makes a browse generic.
    "cics": frozenset("""UPDATE NOHANDLE GTEQ EQUAL GENERIC RRN RBA XRBA MASSINSERT
           NOSUSPEND NOQUEUE ERASE ERASEAUP FREEKB ALARM FRSET PRINT
           CURSOR WAIT MAIN AUXILIARY PROTECT LAST ACCUM PAGING TERMINAL
           IMMEDIATE COMMAREA TRANSACTION NOEDIT DEFRESP""".split()),
}

_EXEC = re.compile(r"^//\S*\s+EXEC\s+(.*)$")
_DDNAME = re.compile(r"^//(\S+)\s+DD\b")
_PARM = re.compile(r"\bPARM=(\((?:[^()]|\([^()]*\))*\)|'[^']*'|[^,\s]+)")
_OPERAND = re.compile(r"\b([A-Z][A-Z0-9#$@]*)\s*=?\s*\(")
_DECK_TERMINATOR = re.compile(r"^(/\*|//)\s*$")


def _verb_of(tokens: list[str], dialect: str) -> str:
    """Collapse a two-word verb into one key; otherwise take the first token."""
    if len(tokens) >= 2:
        pair = f"{tokens[0]} {tokens[1]}"
        if pair in _TWO_WORD_VERBS.get(dialect, frozenset()):
            return pair.replace(" ", "_")
    return tokens[0]


def _scan_operands(
    stmt: str, verb: str, prefix: str, found: Counter[str], dialect: str = "idcams"
) -> None:
    verb_words = set(verb.split("_"))
    for operand in _OPERAND.findall(stmt):
        if operand not in verb_words:
            found[f"{prefix}.{operand}"] += 1
    for bare in _BARE_OPERANDS.get(dialect, frozenset()):
        if bare not in verb_words and re.search(
            rf"(?<![A-Z0-9-]){bare}(?![A-Z0-9(-])", stmt
        ):
            found[f"{prefix}.{bare}"] += 1


class _StepScanner:
    """Tracks the current step so a control deck is attributed to its tool."""

    def __init__(self, found: Counter[str]) -> None:
        self.found = found
        self.tool = ""
        self.dialect = ""
        self.control_dds: frozenset[str] = frozenset()
        self.registered = False
        self.deck_dd = ""
        self.pending = ""
        self.in_dsn = False

    # -- JCL side ---------------------------------------------------------
    def exec_statement(self, operands: str) -> None:
        self.flush()
        self.in_dsn = False
        pgm = re.search(r"\bPGM=([^,\s]+)", operands)
        if not pgm:
            proc = re.search(r"\bPROC=([^,\s]+)", operands) or re.match(
                r"\s*([A-Z@#$][A-Z0-9@#$]*)", operands
            )
            if proc:
                self.found[f"PROC.{proc.group(1)}"] += 1
            self.tool = ""
            return

        self.tool = pgm.group(1).upper()
        self.found[f"TOOL.{self.tool}"] += 1
        self.dialect, self.control_dds = _TOOLS.get(self.tool, ("unknown", frozenset()))
        self.registered = self.tool in _TOOLS
        if not self.registered:
            self.found[f"TOOL.{self.tool}.UNREGISTERED"] += 1
        for value in _PARM.findall(operands):
            for token in re.split(r"[,\s]+", value.strip("()'\" ")):
                if token:
                    self.found[f"TOOL.{self.tool}.PARM.{token.upper()}"] += 1

    def dd_statement(self, line: str) -> None:
        self.flush()
        name = _DDNAME.match(line)
        ddname = name.group(1).upper() if name else ""
        if self.tool and not self.registered and ddname:
            self.found[f"TOOL.{self.tool}.DD.{ddname}"] += 1
        self.deck_dd = ddname if _DECK_START.search(line) else ""

    # -- deck side --------------------------------------------------------
    def deck_line(self, raw: str) -> None:
        if not self.tool or not self.deck_dd:
            return
        if self.registered and self.deck_dd not in self.control_dds:
            return
        line = raw[:72].rstrip().upper()
        if not line.strip():
            return
        self.pending += " " + line.strip().rstrip("-+")
        if line.rstrip().endswith(("-", "+", ",")):
            return
        self.flush()

    def flush(self) -> None:
        stmt, self.pending = self.pending.strip(), ""
        if not stmt:
            return
        if self.dialect == "iebupdte":
            stmt = stmt.lstrip("./ ")
        tokens = re.findall(r"[A-Z][A-Z0-9#$@]*", stmt)
        if not tokens:
            return

        if not self.registered:
            self.found[f"TOOL.{self.tool}.DECK.{tokens[0]}"] += 1
            return

        if self.dialect == "tso":
            self._tso(stmt, tokens)
            return
        verb = _verb_of(tokens, self.dialect)
        prefix = f"TOOL.{self.tool}.{verb}"
        self.found[prefix] += 1
        _scan_operands(stmt, verb, prefix, self.found)

    def _tso(self, stmt: str, tokens: list[str]) -> None:
        """SYSTSIN nests: a DSN command opens a Db2 subcommand scope."""
        if self.in_dsn and tokens[0] != "END":
            verb = _verb_of(tokens, "tso_dsn")
            prefix = f"TOOL.{self.tool}.DSN.{verb}"
            self.found[prefix] += 1
            _scan_operands(stmt, verb, prefix, self.found)
            return
        if tokens[0] == "END":
            self.in_dsn = False
            return
        self.found[f"TOOL.{self.tool}.{tokens[0]}"] += 1
        self.in_dsn = tokens[0] == "DSN"


# --------------------------------------------------------------------------
# Embedded languages: EXEC CICS / EXEC SQL / EXEC DLI, and BMS macros.
# --------------------------------------------------------------------------

# Verbs whose second word changes the command.
_CICS_TWO_WORD = _phrases(
    """SEND MAP|SEND TEXT|SEND CONTROL|SEND PAGE|SEND JSON|RECEIVE MAP|
       RECEIVE JSON|WRITEQ TS|WRITEQ TD|READQ TS|READQ TD|DELETEQ TS|
       DELETEQ TD|HANDLE CONDITION|HANDLE AID|HANDLE ABEND|IGNORE CONDITION|
       PUSH HANDLE|POP HANDLE|PUT CONTAINER|GET CONTAINER|MOVE CONTAINER|
       DELETE CONTAINER|START TRANSID|INVOKE SERVICE|WRITE JOURNALNAME|
       WAIT JOURNALNAME|WEB SEND|WEB RECEIVE|WEB OPEN|WEB CLOSE|
       DOCUMENT CREATE|DOCUMENT INSERT|DOCUMENT RETRIEVE"""
)

# Functional areas: which CICS subsystem a command actually exercises.
_CICS_AREAS: dict[str, str] = {
    verb: area
    for area, verbs in {
        "FILE_CONTROL": """READ WRITE REWRITE DELETE UNLOCK STARTBR READNEXT
                           READPREV ENDBR RESETBR""",
        "TERMINAL_BMS": "SEND SEND_MAP SEND_TEXT SEND_CONTROL SEND_PAGE "
        "RECEIVE RECEIVE_MAP CONVERSE",
        "TEMP_STORAGE": "WRITEQ_TS READQ_TS DELETEQ_TS",
        "TRANSIENT_DATA": "WRITEQ_TD READQ_TD DELETEQ_TD",
        "INTERVAL_CONTROL": """ASKTIME FORMATTIME DELAY START START_TRANSID
                               CANCEL RETRIEVE POST WAIT""",
        "TASK_CONTROL": "ENQ DEQ SUSPEND",
        "PROGRAM_CONTROL": "LINK XCTL RETURN LOAD RELEASE INVOKE_SERVICE",
        "STORAGE": "GETMAIN FREEMAIN",
        "UNIT_OF_WORK": "SYNCPOINT ROLLBACK",
        "CHANNEL": "PUT_CONTAINER GET_CONTAINER MOVE_CONTAINER "
        "DELETE_CONTAINER STARTBROWSE_CONTAINER",
        "JOURNALLING": "WRITE_JOURNALNAME WAIT_JOURNALNAME",
        "ABEND_HANDLING": "ABEND HANDLE_ABEND HANDLE_CONDITION HANDLE_AID "
        "IGNORE_CONDITION PUSH_HANDLE POP_HANDLE",
        "SPI": "INQUIRE SET PERFORM COLLECT DISCARD CREATE",
        "WEB": "WEB_SEND WEB_RECEIVE WEB_OPEN WEB_CLOSE DOCUMENT_CREATE "
        "DOCUMENT_INSERT DOCUMENT_RETRIEVE",
        "ASSIGN_ADDRESS": "ASSIGN ADDRESS",
    }.items()
    for verb in verbs.split()
}

_EXEC_BLOCK = re.compile(
    r"\bEXEC\s+(CICS|SQL|DLI)\b(.*?)(?:END-EXEC|END_EXEC)", re.DOTALL | re.IGNORECASE
)
_BMS_MACRO = re.compile(r"^\S*\s+(DFH[A-Z]{3})\b", re.MULTILINE)
_COBOL_COMMENT = re.compile(r"^[\d ]{6}[*/]")


def _uncommented(text: str) -> str:
    """Drop COBOL comment lines (an indicator in column 7)."""
    return "\n".join(
        line for line in text.splitlines() if not _COBOL_COMMENT.match(line)
    )


def _scan_embedded(text: str, found: Counter[str]) -> None:
    body = _uncommented(text)

    for language, statement in _EXEC_BLOCK.findall(body):
        stmt = " ".join(statement.upper().split())
        tokens = re.findall(r"[A-Z][A-Z0-9#$@]*", stmt)
        if not tokens:
            continue
        if language.upper() != "CICS":
            found[f"{language.upper()}.{tokens[0]}"] += 1
            continue

        pair = " ".join(tokens[:2])
        verb = pair.replace(" ", "_") if pair in _CICS_TWO_WORD else tokens[0]
        prefix = f"CICS.{verb}"
        found[prefix] += 1
        _scan_operands(stmt, verb, prefix, found, dialect="cics")
        area = _CICS_AREAS.get(verb)
        if area:
            found[f"CICS.AREA.{area}"] += 1

    for macro in _BMS_MACRO.findall(body):
        found[f"BMS.{macro}"] += 1


def scan_text(text: str) -> Counter[str]:
    """Inventory every mainframe feature key visible in one file's text."""
    found: Counter[str] = Counter()
    _scan_embedded(text, found)
    steps = _StepScanner(found)

    for line in jcl_lines(text):
        if not line.startswith("//"):
            if _DECK_TERMINATOR.match(line) or _JES_CARD.match(line):
                steps.flush()
                steps.deck_dd = ""
                _scan_jcl(line, found)
            else:
                steps.deck_line(line)
            continue

        _scan_jcl(line, found)
        exec_stmt = _EXEC.match(line)
        if exec_stmt:
            steps.exec_statement(exec_stmt.group(1))
        elif re.match(r"^//\S*\s+DD\b", line):
            steps.dd_statement(line)
        else:
            steps.flush()
    steps.flush()
    return found


def jcl_lines(text: str) -> list[str]:
    """Normalize JCL cards into logical lines.

    Strips cols 73-80, drops //* comments, and joins continuations. In-stream
    deck payload (DD * / DD DATA) is passed through verbatim — it is the
    utility's own control language, not JCL.
    """
    out: list[str] = []
    in_deck = False
    pending = ""

    for raw in text.splitlines():
        if in_deck and not raw.startswith("//"):
            out.append(raw)
            if raw.startswith("/*"):
                in_deck = False
            continue
        in_deck = False

        line = raw[:72].rstrip()
        if not line or line.startswith("//*"):
            continue

        if pending:
            pending += line[2:].lstrip() if line.startswith("//") else line.lstrip()
        else:
            pending = line

        if pending.endswith(","):
            continue

        out.append(pending)
        in_deck = bool(_DECK_START.search(pending))
        pending = ""

    if pending:
        out.append(pending)
    return out


# --------------------------------------------------------------------------
# Discovery, aggregation, reporting.
# --------------------------------------------------------------------------

_SKIP_DIRS = frozenset(
    """.git .hg .svn node_modules __pycache__ .venv venv target build dist
       .mypy_cache .pytest_cache .ruff_cache .idea .gradle""".split()
)
_MAX_BYTES = 8 * 1024 * 1024


@dataclass
class Inventory:
    """Feature key -> how many occurrences, and which files they came from."""

    counts: Counter[str] = field(default_factory=Counter)
    files: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    scanned: int = 0

    def add(self, path: str, found: Counter[str]) -> None:
        self.scanned += 1
        for key, count in found.items():
            self.counts[key] += count
            self.files[key].add(path)


def iter_files(root: Path) -> Iterator[Path]:
    """Every file under root, extension irrelevant — real corpora keep JCL in
    extensionless PROCLIB members as often as in *.jcl."""
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def read_text(path: Path) -> str:
    """Decode a source file, or return '' if it is binary or unreadable."""
    try:
        if path.stat().st_size > _MAX_BYTES:
            return ""
        raw = path.read_bytes()
    except OSError:
        return ""
    if b"\x00" in raw[:4096]:
        return ""
    return raw.decode("utf-8", errors="replace")


def build_inventory(roots: list[Path]) -> Inventory:
    inv = Inventory()
    for root in roots:
        for path in iter_files(Path(root)):
            text = read_text(path)
            if text:
                inv.add(str(path), scan_text(text))
    return inv


def format_report(inv: Inventory, category: str = "", by_file: bool = False) -> str:
    rows = [
        (key, count)
        for key, count in inv.counts.items()
        if not category or key.split(".")[0] == category
    ]
    rows.sort(key=lambda kv: (-kv[1], kv[0]))
    width = max((len(k) for k, _ in rows), default=0)

    out = []
    for key, count in rows:
        out.append(f"{key.ljust(width)}  {count:>6}  {len(inv.files[key]):>5} files")
        if by_file:
            out.extend(f"{'':{width}}    {p}" for p in sorted(inv.files[key]))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", type=Path, help="files or directories to scan")
    ap.add_argument("--category", default="", help="e.g. TOOL, CICS, JCL, SQL, BMS")
    ap.add_argument("--by-file", action="store_true", help="list the source files")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    inv = build_inventory(args.roots)
    if args.json:
        print(
            json.dumps(
                {
                    "scanned_files": inv.scanned,
                    "features": {
                        k: {"count": c, "files": sorted(inv.files[k])}
                        for k, c in sorted(inv.counts.items())
                    },
                },
                indent=2,
            )
        )
    else:
        print(format_report(inv, args.category, args.by_file))
        print(f"\nscanned {inv.scanned} files", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
