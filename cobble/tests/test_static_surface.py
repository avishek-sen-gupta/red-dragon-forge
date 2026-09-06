import subprocess
import sys


def test_cobble_can_reach_the_byte_extent_algebra():
    from cobol_memory.field_extent import FieldExtent, Precision
    from cobol_memory.region_id import RegionId

    exact_extent = FieldExtent(
        region=RegionId.WORKING_STORAGE,
        start=0,
        length=100,
        precision=Precision.EXACT,
        field_name="FLD-EXACT",
    )
    clamped_extent = FieldExtent(
        region=RegionId.WORKING_STORAGE,
        start=0,
        length=100,
        precision=Precision.CLAMPED,
        field_name="FLD-CLAMPED",
    )
    contained_extent = FieldExtent(
        region=RegionId.WORKING_STORAGE,
        start=10,
        length=20,
        precision=Precision.EXACT,
        field_name="FLD-CONTAINED",
    )

    assert exact_extent.must_cover(contained_extent)
    assert not clamped_extent.must_cover(contained_extent)
    assert exact_extent.may_alias(contained_extent)
    assert clamped_extent.may_alias(contained_extent)


def test_reaching_it_does_not_drag_in_the_interpreter():
    """cobble-no-interpreter is a static contract; this is its runtime twin.

    import-linter sees import statements. It cannot see that importing
    cobol_memory would execute interpreter/__init__.py and load the VM.
    """
    code = (
        "import sys;"
        "import cobol_memory.field_extent;"
        "print(any(m == 'interpreter' or m.startswith('interpreter.')"
        " for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
