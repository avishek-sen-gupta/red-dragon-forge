from dataclasses import FrozenInstanceError
import pytest
from tests.covers import covers, NotLanguageFeature
from cics.flow_observer import CicsVerb, NullCicsFlowObserver, field_direction
from bms_copybook_gen.models import BmsField


class _CapturingObserver:
    def __init__(self):
        self.captured: list[CicsVerb] = []

    def on_verb(self, verb: CicsVerb) -> None:
        self.captured.append(verb)


def _minimal_ctx():
    from interpreter.register import Register

    class _Ctx:
        def __init__(self):
            self.emitted = []
            self._n = 0

        def fresh_reg(self):
            self._n += 1
            return Register(f"%r{self._n}")

        def emit_inst(self, inst):
            self.emitted.append(inst)

        def group_leaf_names(self, group_name, materialised):
            return []

        def has_field(self, name, materialised):
            return False

    return _Ctx()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cics_verb_is_frozen():
    v = CicsVerb(
        verb="SEND_MAP",
        program="PROG1",
        map_name="MAP1",
        mapset_name="SET1",
        xctl_target=None,
        transid=None,
    )
    with pytest.raises((FrozenInstanceError, AttributeError)):
        v.verb = "OTHER"  # type: ignore[misc]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cics_verb_optional_fields_default_none():
    v = CicsVerb(
        verb="XCTL",
        program="PROG1",
        map_name=None,
        mapset_name=None,
        xctl_target="PROG2",
        transid=None,
    )
    assert v.map_name is None
    assert v.transid is None
    assert v.xctl_target == "PROG2"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_null_observer_on_verb_is_noop():
    observer = NullCicsFlowObserver()
    v = CicsVerb(
        verb="SEND_MAP",
        program="PROG1",
        map_name="MAP1",
        mapset_name="SET1",
        xctl_target=None,
        transid=None,
    )
    assert observer.on_verb(v) is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_map_notifies_observer():
    import queue
    from interpreter.cobol.cobol_statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="SEND MAP",
        options={
            "MAP": CicsOperand("CACTVWA", True),
            "MAPSET": CicsOperand("COACTVW", True),
        },
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    assert len(observer.captured) == 1
    v = observer.captured[0]
    assert v.verb == "SEND_MAP"
    assert v.map_name == "CACTVWA"
    assert v.mapset_name == "COACTVW"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_xctl_notifies_observer():
    from interpreter.cobol.cobol_statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="XCTL",
        options={"PROGRAM": CicsOperand("COSGN00C", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    assert len(observer.captured) == 1
    v = observer.captured[0]
    assert v.verb == "XCTL"
    assert v.xctl_target == "COSGN00C"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_return_transid_notifies_observer():
    from interpreter.cobol.cobol_statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="RETURN",
        options={"TRANSID": CicsOperand("CA00", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    assert len(observer.captured) == 1
    v = observer.captured[0]
    assert v.verb == "RETURN_TRANSID"
    assert v.transid == "CA00"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_null_observer_is_default():
    from interpreter.cobol.cobol_statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
    )
    stmt = ExecCicsStatement(
        verb="XCTL",
        options={"PROGRAM": CicsOperand("COSGN00C", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)  # must not raise


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unprot_field_is_input():
    f = BmsField(label="ACCTSID", length=11, attrb=["UNPROT"])
    assert field_direction(f) == "input"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_prot_field_is_output():
    f = BmsField(label="ACCTNAME", length=50, attrb=["PROT", "BRT"])
    assert field_direction(f) == "output"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_askip_field_is_output():
    f = BmsField(label="HDNG", length=40, attrb=["ASKIP"])
    assert field_direction(f) == "output"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_attrb_defaults_to_input():
    f = BmsField(label="INPUTFLD", length=10, attrb=[])
    assert field_direction(f) == "input"
