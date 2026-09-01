"""PROC expansion: symbol substitution, DD overriding, nesting.

``parse_proc`` is stubbed so no JVM starts -- each PROC's parsed shape is built
here, the same way tests/jackal/test_jcl_graph.py builds a Job. The .prc file on
disk still has to exist, because that is how a PROC name resolves to a PROC; its
text is the PROC's name, and the stub looks the ProcDef up by it.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from jackal.dsn import DirectDSN, TempRef
from jackal.jcl import proc_expand
from jackal.jcl.proc_expand import ProcExpansionError, expand_procs
from jackal.model import DD, Disp, DispNormal, DispStatus, Job, ProcDef, Step
from jackal.value_parts import Symbol, Value, literal, resolve

_NEW = Disp(DispStatus.NEW, DispNormal.PASS, DispNormal.PASS)
_SHR = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)
_NOTHING_BOUND: Mapping[str, Value] = {}


def _dd(ddname: str, dsn: DirectDSN, disp: Disp = _NEW) -> DD:
    return DD(ddname=ddname, dsn=dsn, disp=disp)


def _one_step_proc(
    *dds: DD, name: str = "PROCONE", defaults: Mapping[str, Value] = _NOTHING_BOUND
) -> ProcDef:
    return ProcDef(
        name=name,
        defaults=dict(defaults),
        steps=(Step(name="INNERONE", pgm="PROGONE", dds=dds),),
    )


def _calling_job(
    proc_parms: Mapping[str, Value] = _NOTHING_BOUND, pgm: str = "PROCONE"
) -> Job:
    return Job(
        name="JOBONE",
        steps=(Step(name="STEPONE", pgm=pgm, dds=(), proc_parms=dict(proc_parms)),),
    )


def _expand(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    procs: tuple[ProcDef, ...],
    job: Job,
) -> Job:
    """Expand ``job`` against a proclib holding exactly these PROCs."""
    for proc in procs:
        (tmp_path / f"{proc.name}.prc").write_text(proc.name)
    by_name = {proc.name: proc for proc in procs}
    monkeypatch.setattr(proc_expand, "parse_proc", lambda text: by_name[text.strip()])
    return expand_procs(job, (tmp_path,))


def _work_dsn(job: Job) -> object:
    return job.steps[0].dds[0].dsn


# ── Symbol substitution ───────────────────────────────────────────


def test_a_proc_parameter_is_substituted_into_the_dsn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reason a lone symbol cannot be reclassified before expansion: this
    DSN is one symbol too, and here it does name a real dataset."""
    expanded = _expand(
        monkeypatch,
        tmp_path,
        (_one_step_proc(_dd("WORK", DirectDSN((Symbol("INFILE"),)))),),
        _calling_job({"INFILE": literal("TEST.DATA")}),
    )
    assert _work_dsn(expanded) == DirectDSN(literal("TEST.DATA"))


def test_a_proc_default_supplies_a_dsn_the_caller_left_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expanded = _expand(
        monkeypatch,
        tmp_path,
        (
            _one_step_proc(
                _dd("WORK", DirectDSN((Symbol("INFILE"),))),
                defaults={"INFILE": literal("TEST.DATA")},
            ),
        ),
        _calling_job(),
    )
    assert _work_dsn(expanded) == DirectDSN(literal("TEST.DATA"))


def test_the_caller_beats_the_proc_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expanded = _expand(
        monkeypatch,
        tmp_path,
        (
            _one_step_proc(
                _dd("WORK", DirectDSN((Symbol("INFILE"),))),
                defaults={"INFILE": literal("DEFAULT.DATA")},
            ),
        ),
        _calling_job({"INFILE": literal("TEST.DATA")}),
    )
    assert _work_dsn(expanded) == DirectDSN(literal("TEST.DATA"))


def test_a_symbol_is_substituted_inside_a_longer_dsn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Asserted through ``resolve`` because substitution splices parts in place
    rather than re-joining them: the value stays two literals, worth one name."""
    expanded = _expand(
        monkeypatch,
        tmp_path,
        (_one_step_proc(_dd("WORK", DirectDSN((Symbol("HLQ"), *literal(".DATA"))))),),
        _calling_job({"HLQ": literal("TEST")}),
    )
    dsn = _work_dsn(expanded)
    assert isinstance(dsn, DirectDSN)
    assert resolve(dsn.name) == "TEST.DATA"


def test_a_symbol_in_a_parm_is_substituted_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = ProcDef(
        name="PROCONE",
        defaults={},
        steps=(Step(name="INNERONE", pgm="PROGONE", dds=(), parm=(Symbol("MODE"),)),),
    )
    expanded = _expand(
        monkeypatch, tmp_path, (proc,), _calling_job({"MODE": literal("TEST")})
    )
    assert expanded.steps[0].parm == literal("TEST")


def test_a_lone_unbound_symbol_in_a_proc_dsn_is_a_temporary_dataset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The sibling of the job-level case: z/OS reads DSN=&WORK1 as DSN=&&WORK1
    when nothing binds WORK1, inside a PROC exactly as outside one.

    The expansion used to raise instead, and the raise escaped the pass -- so a
    member lost every step, program and dataset it had over one work file, the
    same total loss dsn_key caused before dsn.temp_if_unresolved.
    """
    expanded = _expand(
        monkeypatch,
        tmp_path,
        (_one_step_proc(_dd("WORK", DirectDSN((Symbol("WORK1"),)))),),
        _calling_job(),
    )
    assert _work_dsn(expanded) == TempRef("&WORK1")


def test_a_symbol_too_long_to_be_a_temp_name_is_an_unbound_parameter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A temporary dataset name is at most 8 characters, so a longer unbound
    symbol is a PROC parameter the caller forgot -- worth reporting as one."""
    with pytest.raises(ProcExpansionError, match="WORKINPUTFILE"):
        _expand(
            monkeypatch,
            tmp_path,
            (_one_step_proc(_dd("WORK", DirectDSN((Symbol("WORKINPUTFILE"),)))),),
            _calling_job(),
        )


def test_an_unbound_symbol_glued_to_literal_text_is_an_unbound_parameter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """&HLQ..DATA is no temporary dataset name whatever &HLQ is worth."""
    with pytest.raises(ProcExpansionError, match="HLQ"):
        _expand(
            monkeypatch,
            tmp_path,
            (
                _one_step_proc(
                    _dd("WORK", DirectDSN((Symbol("HLQ"), *literal(".DATA"))))
                ),
            ),
            _calling_job(),
        )


def test_an_unbound_symbol_in_a_parm_is_still_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The temp-dataset reading belongs to DSNs. A PARM is not a dataset name,
    so nothing there can stand in for &&NAME."""
    proc = ProcDef(
        name="PROCONE",
        defaults={},
        steps=(Step(name="INNERONE", pgm="PROGONE", dds=(), parm=(Symbol("MODE"),)),),
    )
    with pytest.raises(ProcExpansionError, match="MODE"):
        _expand(monkeypatch, tmp_path, (proc,), _calling_job())


def test_a_non_direct_dsn_carries_through_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = ProcDef(
        name="PROCONE",
        defaults={},
        steps=(
            Step(
                name="INNERONE",
                pgm="PROGONE",
                dds=(DD(ddname="WORK", dsn=TempRef("&&WORKIN"), disp=_NEW),),
            ),
        ),
    )
    expanded = _expand(monkeypatch, tmp_path, (proc,), _calling_job())
    assert _work_dsn(expanded) == TempRef("&&WORKIN")


# ── Step naming, DD overrides, nesting ────────────────────────────


def test_an_expanded_step_is_named_for_the_step_that_called_the_proc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expanded = _expand(
        monkeypatch,
        tmp_path,
        (_one_step_proc(_dd("WORK", DirectDSN(literal("TEST.DATA")))),),
        _calling_job(),
    )
    assert [step.name for step in expanded.steps] == ["STEPONE.INNERONE"]


def test_a_step_that_resolves_to_no_proc_file_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = Job(name="JOBONE", steps=(Step(name="STEPONE", pgm="PROGONE", dds=()),))
    assert (
        _expand(
            monkeypatch,
            tmp_path,
            (_one_step_proc(_dd("WORK", DirectDSN(literal("TEST.DATA")))),),
            job,
        )
        == job
    )


def test_a_qualified_override_replaces_the_inner_dd_of_that_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = Job(
        name="JOBONE",
        steps=(
            Step(
                name="STEPONE",
                pgm="PROCONE",
                dds=(_dd("INNERONE.WORK", DirectDSN(literal("OVERRIDE.DATA")), _SHR),),
            ),
        ),
    )
    expanded = _expand(
        monkeypatch,
        tmp_path,
        (_one_step_proc(_dd("WORK", DirectDSN(literal("TEST.DATA")))),),
        job,
    )
    assert expanded.steps[0].dds == (
        _dd("WORK", DirectDSN(literal("OVERRIDE.DATA")), _SHR),
    )


def test_a_qualified_override_of_an_unknown_ddname_is_appended(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = Job(
        name="JOBONE",
        steps=(
            Step(
                name="STEPONE",
                pgm="PROCONE",
                dds=(_dd("INNERONE.EXTRA", DirectDSN(literal("EXTRA.DATA"))),),
            ),
        ),
    )
    expanded = _expand(
        monkeypatch,
        tmp_path,
        (_one_step_proc(_dd("WORK", DirectDSN(literal("TEST.DATA")))),),
        job,
    )
    assert [dd.ddname for dd in expanded.steps[0].dds] == ["WORK", "EXTRA"]


def test_an_unqualified_override_applies_to_a_single_step_proc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = Job(
        name="JOBONE",
        steps=(
            Step(
                name="STEPONE",
                pgm="PROCONE",
                dds=(_dd("WORK", DirectDSN(literal("OVERRIDE.DATA")), _SHR),),
            ),
        ),
    )
    expanded = _expand(
        monkeypatch,
        tmp_path,
        (_one_step_proc(_dd("WORK", DirectDSN(literal("TEST.DATA")))),),
        job,
    )
    assert _work_dsn(expanded) == DirectDSN(literal("OVERRIDE.DATA"))


def test_an_unqualified_override_is_ignored_by_a_multi_step_proc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With more than one inner step there is no telling which step it meant."""
    proc = ProcDef(
        name="PROCONE",
        defaults={},
        steps=(
            Step(
                name="INNERONE",
                pgm="PROGONE",
                dds=(_dd("WORK", DirectDSN(literal("TEST.DATA"))),),
            ),
            Step(name="INNERTWO", pgm="PROGTWO", dds=()),
        ),
    )
    job = Job(
        name="JOBONE",
        steps=(
            Step(
                name="STEPONE",
                pgm="PROCONE",
                dds=(_dd("WORK", DirectDSN(literal("OVERRIDE.DATA"))),),
            ),
        ),
    )
    expanded = _expand(monkeypatch, tmp_path, (proc,), job)
    assert _work_dsn(expanded) == DirectDSN(literal("TEST.DATA"))


def test_a_proc_calling_a_proc_is_expanded_all_the_way_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outer = ProcDef(
        name="PROCONE",
        defaults={},
        steps=(Step(name="INNERONE", pgm="PROCTWO", dds=()),),
    )
    inner = ProcDef(
        name="PROCTWO",
        defaults={},
        steps=(Step(name="INNERTWO", pgm="PROGONE", dds=()),),
    )
    expanded = _expand(monkeypatch, tmp_path, (outer, inner), _calling_job())
    assert [(step.name, step.pgm) for step in expanded.steps] == [
        ("STEPONE.INNERONE.INNERTWO", "PROGONE")
    ]


def test_a_proc_that_calls_itself_is_reported_rather_than_recursed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = ProcDef(
        name="PROCONE",
        defaults={},
        steps=(Step(name="INNERONE", pgm="PROCONE", dds=()),),
    )
    with pytest.raises(ProcExpansionError, match="Circular PROC reference"):
        _expand(monkeypatch, tmp_path, (proc,), _calling_job())


def test_a_missing_proc_in_one_proclib_is_looked_for_in_the_next(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = _one_step_proc(_dd("WORK", DirectDSN(literal("TEST.DATA"))))
    (tmp_path / "PROCONE.prc").write_text(proc.name)
    monkeypatch.setattr(proc_expand, "parse_proc", lambda _text: proc)
    empty = tmp_path / "empty"
    empty.mkdir()
    expanded = expand_procs(_calling_job(), (empty, tmp_path))
    assert [step.name for step in expanded.steps] == ["STEPONE.INNERONE"]


def test_every_step_of_a_job_is_expanded_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = ProcDef(
        name="PROCONE",
        defaults={},
        steps=(
            Step(name="INNERONE", pgm="PROGONE", dds=()),
            Step(name="INNERTWO", pgm="PROGTWO", dds=()),
        ),
    )
    job = Job(
        name="JOBONE",
        steps=(
            Step(name="STEPONE", pgm="PROCONE", dds=()),
            Step(name="STEPTWO", pgm="PROGTHREE", dds=()),
            Step(name="STEPTHREE", pgm="PROCONE", dds=()),
        ),
    )
    expanded = _expand(monkeypatch, tmp_path, (proc,), job)
    assert [step.name for step in expanded.steps] == [
        "STEPONE.INNERONE",
        "STEPONE.INNERTWO",
        "STEPTWO",
        "STEPTHREE.INNERONE",
        "STEPTHREE.INNERTWO",
    ]
