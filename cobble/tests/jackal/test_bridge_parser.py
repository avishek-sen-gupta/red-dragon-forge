"""DISP subparameter defaults when the JCL omits them.

``DISP=(status,normal,abnormal)`` may omit any positional subparameter, and may
be absent from a DD altogether. The parser keeps an omitted subparameter as
``Omitted``; the defaults depend on each other and on whether the data set
existed, so ``Disp.resolved(existed)`` applies them (IBM MVS JCL Reference,
DISP Defaults).
"""

from jackal.jcl.wire import disp_from_words
from jackal.model import (
    Disp,
    DispAbnormal,
    DispNormal,
    DispStatus,
    Omitted,
    ResolvedDisp,
)


def test_all_three_subparameters_given() -> None:
    assert disp_from_words(("NEW", "CATLG", "DELETE")) == Disp(
        DispStatus.NEW, DispNormal.CATLG, DispAbnormal.DELETE
    )


def test_omitted_abnormal_disposition_repeats_the_normal_one() -> None:
    disp = disp_from_words(("NEW", "CATLG"))
    assert (disp, disp.resolved(existed=False)) == (
        Disp(DispStatus.NEW, DispNormal.CATLG, Omitted()),
        ResolvedDisp(DispNormal.CATLG, DispAbnormal.CATLG),
    )


def test_omitted_status_defaults_to_new_and_pass_is_not_an_abnormal_disposition() -> (
    None
):
    # DISP=(,PASS) — the empty leading slot reaches us as "". After PASS the
    # abnormal disposition is DELETE for a new dataset, KEEP for an existing one.
    new, old = disp_from_words(("", "PASS")), disp_from_words(("OLD", "PASS"))
    assert (new, old, new.resolved(existed=False), old.resolved(existed=True)) == (
        Disp(DispStatus.NEW, DispNormal.PASS, Omitted()),
        Disp(DispStatus.OLD, DispNormal.PASS, Omitted()),
        ResolvedDisp(DispNormal.PASS, DispAbnormal.DELETE),
        ResolvedDisp(DispNormal.PASS, DispAbnormal.KEEP),
    )


def test_omitted_normal_disposition_defaults_to_delete_for_a_new_dataset() -> None:
    disp = disp_from_words(("NEW",))
    assert (disp, disp.resolved(existed=False)) == (
        Disp(DispStatus.NEW, Omitted(), Omitted()),
        ResolvedDisp(DispNormal.DELETE, DispAbnormal.DELETE),
    )


def test_omitted_normal_disposition_defaults_to_keep_for_an_existing_dataset() -> None:
    disp = disp_from_words(("SHR",))
    assert (disp, disp.resolved(existed=True)) == (
        Disp(DispStatus.SHR, Omitted(), Omitted()),
        ResolvedDisp(DispNormal.KEEP, DispAbnormal.KEEP),
    )


def test_an_inner_omitted_slot_takes_its_default_not_the_next_word() -> None:
    # DISP=(NEW,,DELETE): the normal disposition is omitted, not shifted.
    disp = disp_from_words(("NEW", "", "DELETE"))
    assert (disp, disp.resolved(existed=False)) == (
        Disp(DispStatus.NEW, Omitted(), DispAbnormal.DELETE),
        ResolvedDisp(DispNormal.DELETE, DispAbnormal.DELETE),
    )


def test_a_dd_with_no_disp_at_all_is_a_dataset_the_step_creates_and_deletes() -> None:
    disp = disp_from_words(())
    assert (disp, disp.resolved(existed=False)) == (
        Disp(DispStatus.NEW, Omitted(), Omitted()),
        ResolvedDisp(DispNormal.DELETE, DispAbnormal.DELETE),
    )
