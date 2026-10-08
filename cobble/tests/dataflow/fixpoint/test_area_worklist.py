from cobble.dataflow.fixpoint.area_kind import AreaKind
from cobble.dataflow.fixpoint.area_need import AreaNeed
from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobble.dataflow.fixpoint.area_table import area_table
from cobble.dataflow.fixpoint.area_worklist import callers, dirtied

COMMAREA = AreaSlot(AreaKind.COMMAREA, 0)
RECEIVES = (("PROGA", (COMMAREA,)), ("PROGB", (COMMAREA,)), ("PROGC", (COMMAREA,)))


def test_a_round_walks_again_only_the_members_whose_inputs_changed() -> None:
    callers_of = callers(
        {
            "PROGA": frozenset({"PROGB"}),
            "PROGB": frozenset({"PROGC"}),
            "PROGC": frozenset(),
            "PROGD": frozenset(),
        }
    )
    before = area_table(
        (
            ("PROGA", AreaNeed()),
            ("PROGB", AreaNeed(entry=((COMMAREA, (0, 8)),))),
            ("PROGC", AreaNeed()),
        ),
        RECEIVES,
        (),
    )
    entry_grew = area_table(
        (
            ("PROGA", AreaNeed()),
            ("PROGB", AreaNeed(entry=((COMMAREA, (0, 16)),))),
            ("PROGC", AreaNeed()),
        ),
        RECEIVES,
        (),
    )
    back_grew = area_table(
        (
            ("PROGA", AreaNeed()),
            ("PROGB", AreaNeed(entry=((COMMAREA, (0, 8)),))),
            ("PROGC", AreaNeed(back=((COMMAREA, (4, 6)),))),
        ),
        RECEIVES,
        (),
    )

    assert [
        dirtied(before, before, callers_of, frozenset({"PROGD"})),
        dirtied(before, entry_grew, callers_of, frozenset()),
        dirtied(before, entry_grew, callers_of, frozenset({"PROGD"})),
        dirtied(before, back_grew, callers_of, frozenset({"PROGD"})),
    ] == [
        frozenset(),
        frozenset({"PROGA"}),
        frozenset({"PROGA", "PROGD"}),
        frozenset({"PROGC"}),
    ]
