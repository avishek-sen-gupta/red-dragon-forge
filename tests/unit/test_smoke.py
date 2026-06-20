import importlib

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_red_dragon_importable():
    run_module = importlib.import_module("interpreter.run")  # vendored red-dragon
    assert hasattr(run_module, "run")
