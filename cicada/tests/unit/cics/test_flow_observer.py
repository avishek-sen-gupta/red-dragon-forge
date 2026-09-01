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
    from interpreter.func_name import FuncName
    from interpreter.instructions import CallFunction
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

        def emit_to_string(self, value_reg):
            # Mirrors the real EmitContext.emit_to_string exactly (see
            # interpreter/cobol/emit_context.py) — VSAM verbs' RESP writeback
            # (emit_resp_writeback) calls this before checking has_field, so
            # the fake needs a real implementation, not just a stub.
            result = self.fresh_reg()
            self.emit_inst(
                CallFunction(
                    result_reg=result, func_name=FuncName("str"), args=(value_reg,)
                )
            )
            return result

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
    assert v.file_name is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cics_verb_stores_file_name():
    v = CicsVerb(
        verb="READ",
        program="PROG1",
        map_name=None,
        mapset_name=None,
        xctl_target=None,
        transid=None,
        file_name="ACCTFILE",
    )
    assert v.file_name == "ACCTFILE"


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
    from cics.statements import ExecCicsStatement, CicsOperand
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
    from cics.statements import ExecCicsStatement, CicsOperand
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
    from cics.statements import ExecCicsStatement, CicsOperand
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


def _lower_source(text: str, observer):
    """Lower one EXEC CICS statement written as source, through the real CICS
    dialect parser, so the verb comes from the grammar and not a hand-built
    ExecCicsStatement."""
    from cics.statements import CicsDialectParser
    from cics.strategy import CicsLoweringStrategy

    stmt = CicsDialectParser().parse({"type": "EXEC_CICS", "exec_cics_text": text})
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_start_transid_notifies_observer():
    """START is the third way a program names another unit of work, after XCTL and
    RETURN TRANSID, and the only asynchronous one. Nothing lowered it, so every
    EXEC CICS START was parsed and dropped."""
    observer = _CapturingObserver()
    _lower_source(
        "EXEC CICS START TRANSID('A123') INTERVAL(000500) END-EXEC", observer
    )

    assert len(observer.captured) == 1
    v = observer.captured[0]
    assert v.verb == "START_TRANSID"
    assert v.transid == "A123"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_start_without_transid_is_not_a_graph_event():
    """TRANSID is optional in the API. With no transaction named there is nothing
    for the graph to point at — the same rule RETURN already follows."""
    observer = _CapturingObserver()
    _lower_source("EXEC CICS START TERMID(EIBTRMID) END-EXEC", observer)

    assert observer.captured == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_notifies_observer_with_file_name():
    from cics.statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="READ",
        options={"FILE": CicsOperand("ACCTFILE", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    assert len(observer.captured) == 1
    v = observer.captured[0]
    assert v.verb == "READ"
    assert v.file_name == "ACCTFILE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_accepts_dataset_synonym_for_file():
    from cics.statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="READ",
        options={"DATASET": CicsOperand("ACCTFILE", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    assert observer.captured[0].file_name == "ACCTFILE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_write_notifies_observer_with_file_name():
    from cics.statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="WRITE",
        options={"FILE": CicsOperand("CUSTDAT", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    v = observer.captured[0]
    assert v.verb == "WRITE"
    assert v.file_name == "CUSTDAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_rewrite_notifies_observer_with_file_name():
    from cics.statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="REWRITE",
        options={"FILE": CicsOperand("CUSTDAT", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    v = observer.captured[0]
    assert v.verb == "REWRITE"
    assert v.file_name == "CUSTDAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_notifies_observer_with_file_name():
    from cics.statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="DELETE",
        options={"FILE": CicsOperand("CARDDAT", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    v = observer.captured[0]
    assert v.verb == "DELETE"
    assert v.file_name == "CARDDAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_startbr_notifies_observer_with_file_name():
    from cics.statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="STARTBR",
        options={"FILE": CicsOperand("CARDAIX", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    v = observer.captured[0]
    assert v.verb == "STARTBR"
    assert v.file_name == "CARDAIX"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_readnext_notifies_observer_with_file_name():
    from cics.statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="READNEXT",
        options={"FILE": CicsOperand("CARDAIX", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    v = observer.captured[0]
    assert v.verb == "READNEXT"
    assert v.file_name == "CARDAIX"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_readprev_notifies_observer_with_file_name():
    from cics.statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="READPREV",
        options={"FILE": CicsOperand("CARDAIX", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    v = observer.captured[0]
    assert v.verb == "READPREV"
    assert v.file_name == "CARDAIX"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_endbr_notifies_observer_with_file_name():
    from cics.statements import ExecCicsStatement, CicsOperand
    from cics.strategy import CicsLoweringStrategy

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="ENDBR",
        options={"FILE": CicsOperand("CARDAIX", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    v = observer.captured[0]
    assert v.verb == "ENDBR"
    assert v.file_name == "CARDAIX"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_null_observer_is_default():
    from cics.statements import ExecCicsStatement, CicsOperand
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
