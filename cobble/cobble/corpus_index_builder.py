"""Reads a corpus and returns the finished CorpusIndex it resolves against.

Split out of corpus_index.py, which is now the lookup alone. Populating the index
means parsing JCL and CSD, i.e. reaching into cobble.jcl and cobble.cics --
and both of those packages consume the index. Keeping the reading here means the
lookup module imports leaf modules only, so the cycle those two directions used
to form is gone rather than deferred behind a TYPE_CHECKING guard.

Only build_graph imports this. Consumers take a CorpusIndex they are handed and
call resolve_file_path on it; none of them builds one.

Every entry is first-wins, matching the ``setdefault`` this replaced: the corpus
is walked in a defined order (glob order for programs, sorted for copybooks) and
a duplicate name later in that order does not displace the file already found.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from types import MappingProxyType

from cics.csd_parse import CsdParseError, parse_csd, parse_csd_files
from cobble.corpus_config import CorpusConfig
from cobble.corpus_index import CorpusIndex
from cobble.jcl.job_steps import StepView, expanded_steps, written_steps
from cobble.matching_files import matching_files
from cobol_asg.source_text import decode_source
from jackal.dsn import InStreamDSN
from jackal.expansion import (
    DirectoryProcLibrary,
    ExpansionFailed,
    ProcLibrary,
    expand_or_fail,
)
from jackal.jcl.bridge_parser import JclParseError
from jackal.jcl.parser import parse_jcl
from jackal.model import Job
from tqdm import tqdm

# How the index turns a member's path into a Job: parse it now, or take it from a
# store that already has. Named because both halves of a corpus build need the
# same members and the second must not pay for them again.
ReadJob = Callable[[Path], Job]

# How the index finds a PROC: the configured proclib directories, read through
# the bridge, unless a caller hands in another library.
Libraries = Callable[[Sequence[Path]], ProcLibrary]

logger = logging.getLogger(__name__)

_Pair = tuple[str, Path]


def _first_wins(pairs: Iterable[_Pair]) -> Mapping[str, Path]:
    """A read-only lookup in which the earliest pair for a key is the one kept.

    Reversed because a later write to the same key wins in a dict, and the
    ``setdefault`` this replaced gave the win to the first.
    """
    return MappingProxyType(dict(reversed(tuple(pairs))))


def _program_pairs(config: CorpusConfig) -> tuple[_Pair, ...]:
    """A program is named by its filename stem -- the corpus's own convention."""
    return tuple(
        (path.stem.upper(), path)
        for path in matching_files(config.cobol_dir, config.cobol_globs)
    )


def _copybook_pairs(copybook_dirs: Sequence[Path]) -> tuple[_Pair, ...]:
    """Every file in every configured copybook dir, one level deep.

    Deliberately extension-agnostic, unlike cobble.diagnosis.copybooks: a name can
    resolve to a file_path here and still fail the ProLeap preprocessor, which
    matches only the configured copybook_extensions.

    A configured directory that does not exist is skipped: a corpus can be
    onboarded before its copybook library is staged.
    """
    return tuple(
        (path.stem.upper(), path)
        for directory in copybook_dirs
        if directory.is_dir()
        for path in sorted(directory.iterdir())
        if path.is_file()
    )


def _proc_files(name: str, proclib_dirs: Sequence[Path]) -> tuple[Path, ...]:
    """The .prc files defining ``name``, in configured proclib order."""
    candidates = tuple(proclib_dir / f"{name}.prc" for proclib_dir in proclib_dirs)
    return tuple(candidate for candidate in candidates if candidate.is_file())


def _directory_library(proclib_dirs: Sequence[Path]) -> ProcLibrary:
    return DirectoryProcLibrary(tuple(proclib_dirs))


@dataclass(frozen=True)
class _Expansion:
    """A job's steps with its PROCs inlined, or its steps as written and why not."""

    steps: tuple[StepView, ...]
    failures: tuple[str, ...] = ()


def _expand(job: Job, path: Path, library: ProcLibrary) -> _Expansion:
    """Inline the job's PROC calls, or report why not and carry on.

    Expansion fails on corpus shape the same way parsing does — a reference
    that resolves to no step, a circular PROC, a .prc that is not valid UTF-8,
    a .prc the grammar rejects. One such member must not abort the index
    build, so the failure is reported and the job's own steps, exactly what
    the JCL states, stay indexed; only the PROCs' inner steps are lost, and
    they are lost from the graph too.

    Narrow on purpose: anything outside this handler is a bug in cobble and must
    surface rather than be filed as a corpus problem and skipped.
    """
    try:
        expanded = expand_or_fail(job, library)
    except (ExpansionFailed, JclParseError, UnicodeDecodeError, OSError) as exc:
        logger.warning(
            "CorpusIndex: JCL %s failed to expand its PROCs: %s", path.name, exc
        )
        return _Expansion(written_steps(job), (f"index JCL {path.name}: {exc}",))
    return _Expansion(expanded_steps(expanded))


def _step_file(step: StepView, proclib_dirs: Sequence[Path], path: Path) -> Path:
    """The file a step is written in: its PROC's .prc, else the JCL itself."""
    procs = tuple(_proc_files(proc.name, proclib_dirs) for proc in step.procs)
    return next(iter(chain.from_iterable(procs)), path)


def _instream_pairs(step_id: str, step: StepView, path: Path) -> tuple[_Pair, ...]:
    """Instream content is literal text in the JCL source itself, even when the
    step is proc-expanded — a PROC cannot carry DD * content of its own, only DD
    overrides."""
    return tuple(
        (f"{step_id}.{named.rendered_name.upper()}", path)
        for named in step.dds
        if isinstance(named.dd.dsn, InStreamDSN)
    )


@dataclass(frozen=True)
class _JclEntries:
    """What one JCL member contributes to the index, or why it contributed nothing."""

    jobs: tuple[_Pair, ...] = ()
    steps: tuple[_Pair, ...] = ()
    instream: tuple[_Pair, ...] = ()
    failures: tuple[str, ...] = ()


def _entries_for(
    job: Job, path: Path, proclib_dirs: Sequence[Path], library: ProcLibrary
) -> _JclEntries:
    """One parsed job's jobs, steps and instream data, keyed as the graph keys them."""
    job_name = job.name.upper()
    expansion = _expand(job, path, library)
    steps = tuple(
        (f"{job_name}.{step.rendered_name.upper()}", step) for step in expansion.steps
    )
    return _JclEntries(
        jobs=((job_name, path),),
        steps=tuple(
            (step_id, _step_file(step, proclib_dirs, path)) for step_id, step in steps
        ),
        instream=tuple(
            chain.from_iterable(
                _instream_pairs(step_id, step, path) for step_id, step in steps
            )
        ),
        failures=expansion.failures,
    )


def _read_member(path: Path) -> Job:
    """One member, parsed with its own JVM. The default reader."""
    return parse_jcl(decode_source(path.read_bytes()))


def _index_jcl_file(
    path: Path, proclib_dirs: Sequence[Path], read_job: ReadJob, library: ProcLibrary
) -> _JclEntries:
    """Index one JCL member, reporting a member cobble cannot read rather than
    raising.

    Narrow on purpose. A parse failure or an unreadable file is corpus shape and
    gets reported; anything else is a bug in cobble and must surface rather than
    be filed as a corpus problem and skipped.
    """
    try:
        job = read_job(path)
    except (JclParseError, OSError) as exc:
        logger.warning("CorpusIndex: JCL %s failed to parse: %s", path.name, exc)
        return _JclEntries(failures=(f"index JCL {path.name}: {exc}",))
    return _entries_for(job, path, proclib_dirs, library)


def _index_jcl(
    config: CorpusConfig, read_job: ReadJob, library: ProcLibrary
) -> tuple[_JclEntries, ...]:
    """Every JCL member, with a progress bar.

    The bar matters here more than anywhere else in the run: with the default
    reader this is one JVM subprocess per member, it runs before any extractor
    and before GraphWriter opens its output, and it is the slowest phase of a
    corpus build. Without it the whole indexing pass is indistinguishable from a
    hang. tqdm writes to stderr, so it survives a stdout pipe.

    A corpus build hands in a JclStore's ``get`` instead, which has already
    parsed every member in parallel, so the bar there tracks deserialization.
    """
    return tuple(
        _index_jcl_file(path, config.proclib_dirs, read_job, library)
        for path in tqdm(
            matching_files(config.jcl_dir, config.jcl_globs),
            desc="index JCL",
            unit="file",
        )
    )


@dataclass(frozen=True)
class _CsdEntries:
    """What one CSD file contributes, or why it contributed nothing."""

    transactions: tuple[_Pair, ...] = ()
    cics_files: tuple[_Pair, ...] = ()
    failures: tuple[str, ...] = ()


def _index_csd_file(csd_file: Path) -> _CsdEntries:
    """Index one CSD, reporting a CSD cobble cannot read rather than raising."""
    try:
        return _CsdEntries(
            transactions=tuple(
                (transid.upper(), csd_file) for transid in parse_csd(csd_file)
            ),
            cics_files=tuple(
                (file_name.upper(), csd_file) for file_name in parse_csd_files(csd_file)
            ),
        )
    except (CsdParseError, OSError) as exc:
        logger.warning("CorpusIndex: CSD %s failed to parse: %s", csd_file.name, exc)
        return _CsdEntries(failures=(f"index CSD {csd_file.name}: {exc}",))


def build_corpus_index(
    config: CorpusConfig,
    read_job: ReadJob = _read_member,
    libraries: Libraries = _directory_library,
) -> CorpusIndex:
    """Read the corpus once and return the index every extractor resolves against.

    Failures are ordered JCL then CSD, i.e. the order the corpus was read in, so
    the run's failure report reads in the order things happened.

    ``read_job`` is how a member becomes a Job, defaulting to parsing it here. A
    corpus build passes a JclStore's ``get``, because the graph pass needs the
    same members again and re-parsing them is the single largest avoidable cost
    in a run; see cobble.jcl.jcl_store.

    BMS maps are absent by construction: bms_dir is not part of CorpusConfig
    today (see BmsConfig), so BMS_MAP resolution stays UNRESOLVED until that is
    threaded through too.
    """
    jcl = _index_jcl(config, read_job, libraries(config.proclib_dirs))
    csd = tuple(map(_index_csd_file, config.csd_files))
    return CorpusIndex(
        programs=_first_wins(_program_pairs(config)),
        copybooks=_first_wins(_copybook_pairs(config.copybook_dirs)),
        jobs=_first_wins(chain.from_iterable(entry.jobs for entry in jcl)),
        steps=_first_wins(chain.from_iterable(entry.steps for entry in jcl)),
        instream=_first_wins(chain.from_iterable(entry.instream for entry in jcl)),
        transactions=_first_wins(
            chain.from_iterable(entry.transactions for entry in csd)
        ),
        cics_files=_first_wins(chain.from_iterable(entry.cics_files for entry in csd)),
        failures=tuple(
            chain(
                chain.from_iterable(entry.failures for entry in jcl),
                chain.from_iterable(entry.failures for entry in csd),
            )
        ),
    )
