"""The per-program sequence: one step per PERFORM site, placed in the arms it runs in.

The CFG below has the shape of COACTVWC's 0000-MAIN: an EVALUATE whose arms each
PERFORM the same paragraph, one of them through a nested IF. A paragraph tree keyed
by target name loses all three facts the diagram exists to show -- that the target
repeats, which arm each call is in, and that the arms are alternatives.
"""

from __future__ import annotations

from cobble.viz.models import Arm
from cobble.viz.render_cmd import _render_program
from cobble.viz.sequence_cmd import extract_per_program


def _label(paragraph: str) -> dict:
    return {"id": f"{paragraph}#label", "kind": "LABEL", "paragraph": paragraph}


def _perform(site: str) -> dict:
    return {
        "id": site,
        "kind": "CALL",
        "transfer": "PERFORM",
        "paragraph": site.split("/")[0],
    }


def _test(node_id: str, text: str) -> dict:
    return {
        "id": node_id,
        "kind": "TEST",
        "paragraph": node_id.split("/")[0],
        "atom": {"text": text},
    }


SITES = (
    ("0000-MAIN/0", "A-PARA"),
    ("0000-MAIN/1.when.0.0", "S-PARA"),
    ("0000-MAIN/1.when.1.0", "P-PARA"),
    ("0000-MAIN/1.when.1.1.then.0", "S-PARA"),
    ("0000-MAIN/1.when.1.1.else.0", "R-PARA"),
    ("0000-MAIN/1.when.1.1.else.1", "S-PARA"),
    ("S-PARA/0.then.0", "A-PARA"),
)

CFG = {
    "program": "PROG",
    "nodes": [
        *(_label(p) for p in ("0000-MAIN", "A-PARA", "S-PARA", "P-PARA", "R-PARA")),
        _test("0000-MAIN/1.when.0#test", "ENTER"),
        _test("0000-MAIN/1.when.1#test", "REENTER"),
        _test("0000-MAIN/1.when.1.1#test", "INPUT-ERROR"),
        _test("S-PARA/0#test", "FLAG"),
        *(_perform(site) for site, _ in SITES),
    ],
    "edges": [
        {"source": site, "target": f"{target}#label", "kind": "PERFORM"}
        for site, target in SITES
    ],
}


def test_every_perform_site_is_a_step_even_when_its_target_repeats():
    steps = extract_per_program(CFG).steps

    assert [one.paragraph for one in steps] == [
        "A-PARA",
        "S-PARA",
        "P-PARA",
        "S-PARA",
        "R-PARA",
        "S-PARA",
    ]


def test_a_perform_inside_a_when_arm_is_conditional():
    steps = extract_per_program(CFG).steps

    assert [one.call_type for one in steps] == [
        "simple",
        "conditional",
        "conditional",
        "conditional",
        "conditional",
        "conditional",
    ]


def test_the_call_type_belongs_to_the_site_and_not_to_the_target():
    """A-PARA is performed unconditionally from 0000-MAIN and conditionally from
    S-PARA; neither call may take the other's type."""
    steps = extract_per_program(CFG).steps

    assert steps[0].call_type == "simple"
    assert steps[1].children[0].call_type == "conditional"


def test_each_step_names_the_arms_it_runs_in_outermost_first():
    steps = extract_per_program(CFG).steps

    assert steps[0].arms == ()
    assert steps[4].arms == (
        Arm(decision="0000-MAIN/1", arm="when.1", label="WHEN REENTER"),
        Arm(decision="0000-MAIN/1.when.1.1", arm="else", label="NOT INPUT-ERROR"),
    )
    assert steps[3].arms[-1] == Arm(
        decision="0000-MAIN/1.when.1.1", arm="then", label="IF INPUT-ERROR"
    )


def test_alternative_arms_render_as_one_alt_block_with_a_nested_one():
    """Each S-PARA call draws S-PARA's own IF around its PERFORM of A-PARA, so that
    block recurs once per call, inside whichever arm the call is in."""
    diagram = _render_program("PROG", extract_per_program(CFG).model_dump(mode="json"))
    lines = [line.strip() for line in diagram.splitlines()]
    opened = sum(1 for line in lines if line.startswith(("alt ", "rect ")))

    assert [line for line in lines if line.startswith(("alt ", "else "))] == [
        "alt WHEN ENTER",
        "alt IF FLAG",
        "else WHEN REENTER",
        "alt IF INPUT-ERROR",
        "alt IF FLAG",
        "else NOT INPUT-ERROR",
        "alt IF FLAG",
    ]
    assert opened == lines.count("end")
    assert sum(1 for line in lines if line.startswith("Note over PROG: S-PARA")) == 3
