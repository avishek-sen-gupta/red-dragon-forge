"""CardDemo JCL parse-parity sweep: four real jobs through the bridge."""

from tests.covers import NotLanguageFeature, covers
from jackal.jcl.parser import parse_jcl


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_carddemo_jobs_parse_via_bridge(carddemo_home, jcl_bridge_jar):
    jcl_dir = carddemo_home / "jcl"
    for name in ["ACCTFILE.jcl", "READACCT.jcl", "TRANBKP.jcl", "DEFGDGB.jcl"]:
        job = parse_jcl((jcl_dir / name).read_text())
        assert job.name and job.steps, f"{name} parsed empty"
