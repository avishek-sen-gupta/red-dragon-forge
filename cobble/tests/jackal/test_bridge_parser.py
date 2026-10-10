"""DISP subparameter defaults when the JCL omits them.

``DISP=(status,normal,abnormal)`` may omit any positional subparameter, and may
be absent from a DD altogether. The defaults are positional and depend on each
other, so they are one rule rather than one fixed fallback triple.
"""

from jackal.jcl.wire import disp_from_words
from jackal.model import Disp, DispAbnormal, DispNormal, DispStatus


def test_all_three_subparameters_given() -> None:
    assert disp_from_words(("NEW", "CATLG", "DELETE")) == Disp(
        DispStatus.NEW, DispNormal.CATLG, DispAbnormal.DELETE
    )


def test_omitted_abnormal_disposition_repeats_the_normal_one() -> None:
    assert disp_from_words(("NEW", "CATLG")) == Disp(
        DispStatus.NEW, DispNormal.CATLG, DispAbnormal.CATLG
    )


def test_omitted_status_defaults_to_new_and_pass_is_not_an_abnormal_disposition() -> (
    None
):
    # DISP=(,PASS) — the empty leading slot reaches us as "". After PASS the
    # abnormal disposition is DELETE for a NEW dataset, KEEP otherwise.
    assert [disp_from_words(("", "PASS")), disp_from_words(("OLD", "PASS"))] == [
        Disp(DispStatus.NEW, DispNormal.PASS, DispAbnormal.DELETE),
        Disp(DispStatus.OLD, DispNormal.PASS, DispAbnormal.KEEP),
    ]


def test_omitted_normal_disposition_defaults_to_delete_for_a_new_dataset() -> None:
    assert disp_from_words(("NEW",)) == Disp(
        DispStatus.NEW, DispNormal.DELETE, DispAbnormal.DELETE
    )


def test_omitted_normal_disposition_defaults_to_keep_for_an_existing_dataset() -> None:
    assert disp_from_words(("SHR",)) == Disp(
        DispStatus.SHR, DispNormal.KEEP, DispAbnormal.KEEP
    )


def test_an_inner_omitted_slot_takes_its_default_not_the_next_word() -> None:
    # DISP=(NEW,,DELETE): the normal disposition is defaulted, not shifted.
    assert disp_from_words(("NEW", "", "DELETE")) == Disp(
        DispStatus.NEW, DispNormal.DELETE, DispAbnormal.DELETE
    )


def test_a_dd_with_no_disp_at_all_is_a_dataset_the_step_creates_and_deletes() -> None:
    assert disp_from_words(()) == Disp(
        DispStatus.NEW, DispNormal.DELETE, DispAbnormal.DELETE
    )
