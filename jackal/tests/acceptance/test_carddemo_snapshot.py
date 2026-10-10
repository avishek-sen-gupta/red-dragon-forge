"""What jackal reads from every CardDemo job matches the frozen snapshot."""

from pathlib import Path

from tests.acceptance.carddemo_facts import (
    EXPECTED_CHANGES,
    SNAPSHOT,
    CardDemoSnapshot,
    facts_for_corpus,
)
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_carddemo_matches_snapshot(carddemo_home: Path, jcl_bridge_jar: str):
    frozen = CardDemoSnapshot.model_validate_json(SNAPSHOT.read_text())
    current = facts_for_corpus(carddemo_home.parent)
    frozen_by_file = {job.file: job for job in frozen.jobs}
    differing = sorted(
        job.file for job in current.jobs if frozen_by_file.get(job.file) != job
    )
    assert (
        sorted(job.file for job in current.jobs),
        differing,
    ) == (
        sorted(frozen_by_file),
        sorted(EXPECTED_CHANGES),
    )
