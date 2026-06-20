import importlib

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_red_dragon_importable():
    # red-dragon's interpreter/__init__.py re-exports a `run` symbol, which
    # shadows the `interpreter.run` submodule on a direct `import interpreter.run`.
    # import_module reaches the submodule itself; do NOT "simplify" to a direct
    # import — it would resolve to the re-exported symbol, not the module.
    run_module = importlib.import_module("interpreter.run")  # vendored red-dragon
    assert hasattr(run_module, "run")
