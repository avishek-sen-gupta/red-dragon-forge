"""A step whose RETURN-CODE is unknown stops the job, or completes with RC 0 and a warning."""

import logging

import pytest
from interpreter.cobol.symbolic_return_code_error import SymbolicReturnCodeError
from interpreter.vm.vm_types import SymbolicValue
from jackal.results import Completed
from jackal.unknown_return_code import RaiseUnknownReturnCode, ZeroUnknownReturnCode
from tests.covers import NotLanguageFeature, covers
from tests.model_build import ran

_UNKNOWN = SymbolicReturnCodeError(SymbolicValue(name="call_result_1"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_strict_strategy_stops_the_job_with_the_error() -> None:
    with pytest.raises(SymbolicReturnCodeError) as stopped:
        RaiseUnknownReturnCode().settle(ran("STEP05", "CBACT01C"), _UNKNOWN)

    assert stopped.value is _UNKNOWN


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_lenient_strategy_completes_with_rc_0_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="jackal.unknown_return_code"):
        result = ZeroUnknownReturnCode().settle(ran("STEP05", "CBACT01C"), _UNKNOWN)

    assert (result, caplog.messages) == (
        Completed(0),
        ["STEP05: RETURN-CODE is unknown after the step; completed with RC 0"],
    )
