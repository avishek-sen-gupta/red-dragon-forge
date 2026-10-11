from pathlib import Path

import pytest
from jackal.catalog import Dataset
from jackal.labels import KsdsLabel, LabelPending, RecordFormat, SequentialLabel
from jackal.system_catalog import NotCataloged, SystemCatalog
from tests.covers import NotLanguageFeature, covers

FB80 = SequentialLabel(RecordFormat.FB, 80)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_dataset_added_to_the_system_is_a_labelled_copy_that_outlives_the_catalog(
    tmp_path: Path,
) -> None:
    source = tmp_path / "upload.dat"
    source.write_bytes(b"A" * 160)
    root = tmp_path / "system"
    added = SystemCatalog(root).add("J.IN", source, FB80)
    source.write_bytes(b"changed")
    reloaded = SystemCatalog(root)
    assert (
        added,
        reloaded.lookup("J.IN"),
        added.path.read_bytes(),
        reloaded.lookup("J.NONE"),
    ) == (
        Dataset("J.IN", root / "datasets" / "J.IN", FB80),
        Dataset("J.IN", root / "datasets" / "J.IN", FB80),
        b"A" * 160,
        NotCataloged(),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_created_and_removed_datasets_are_recorded_for_later_catalogs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "system"
    system = SystemCatalog(root)
    created = system.create("J.NEW", LabelPending())
    ksds = system.create("J.KSDS", KsdsLabel(300, 0, 11))
    gone = system.create("J.GONE", FB80)
    system.remove("J.GONE")
    reloaded = SystemCatalog(root)
    assert (
        reloaded.lookup("J.NEW"),
        reloaded.lookup("J.KSDS"),
        reloaded.lookup("J.GONE"),
        created.path.read_bytes(),
        gone.path.exists(),
        ksds.path.exists(),
    ) == (created, ksds, NotCataloged(), b"", False, True)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_label_without_a_record_length_or_key_is_refused() -> None:
    with pytest.raises(ValueError, match="LRECL must be > 0"):
        SequentialLabel(RecordFormat.F, 0)
    with pytest.raises(ValueError, match="key length must be > 0"):
        KsdsLabel(300, 0, 0)
