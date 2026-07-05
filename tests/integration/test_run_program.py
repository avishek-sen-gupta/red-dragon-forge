from __future__ import annotations

import pytest

from interpreter.project.coprocessor_compile import CoprocessorSpec
from red_dragon_forge.run import run_program


def test_raises_when_no_spec_owns_execution():
    specs = [CoprocessorSpec(name="sql", make_strategy=lambda: object(), owns_execution=False)]
    with pytest.raises(NotImplementedError):
        run_program(linked=object(), specs=specs)


def test_raises_when_more_than_one_spec_owns_execution():
    specs = [
        CoprocessorSpec(name="a", make_strategy=lambda: object(), owns_execution=True),
        CoprocessorSpec(name="b", make_strategy=lambda: object(), owns_execution=True),
    ]
    with pytest.raises(AssertionError):
        run_program(linked=object(), specs=specs)
