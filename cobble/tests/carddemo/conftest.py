"""CardDemo, parsed from its source and run through extents and the fixpoint, once per session."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from cobble.corpus_config import CorpusConfig, load_bms_config, load_corpus_config
from cobble.dataflow.combine.cli import cli as combine
from cobble.dataflow.fields.emit_extents import emit
from cobble.dataflow.fields.extents_options import ExtentsOptions
from cobble.dataflow.fixpoint.build_corpus import cli
from cobble.generate_sym import HLASM, generate
from cobble.parsing.parse_corpus import parse_one, pending

COBBLE = Path(__file__).resolve().parents[2]
FORGE = COBBLE.parent
CONFIG = COBBLE / "config" / "carddemo-partition.toml"
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"
# EXEC DLI has no grammar in the bridge (CBPAUP0C, COPAUA0C, COPAUS0C, COPAUS1C),
# and CardDemo does not ship the MQ copybook CMQGMOV (COACCT01, CODATE01).
UNPARSED = {"CBPAUP0C", "COPAUA0C", "COPAUS0C", "COPAUS1C", "COACCT01", "CODATE01"}


@dataclass(frozen=True)
class CardDemoRun:
    extents: Path
    fixpoint: Path
    combine: Path
    asg: Path
    cobol: Path


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def _here(path: Path) -> Path:
    return path if path.is_absolute() else COBBLE / path


def _toml(config: CorpusConfig) -> str:
    """The corpus table the combine's command reads, naming this run's own cache."""
    entries = {
        "cobol_dir": str(config.cobol_dir),
        "cobol_globs": list(config.cobol_globs),
        "jcl_dir": str(_here(config.jcl_dir)),
        "jcl_globs": list(config.jcl_globs),
        "csd_files": [str(_here(path)) for path in config.csd_files],
        "copybook_dirs": [str(path) for path in config.copybook_dirs],
        "asg_dir": str(config.asg_dir),
    }
    return "[corpus]\n" + "".join(
        f"{key} = {json.dumps(value)}\n" for key, value in entries.items()
    )


@pytest.fixture(scope="session")
def carddemo(tmp_path_factory: pytest.TempPathFactory) -> CardDemoRun:
    jar = _bridge_jar()
    if not HLASM.is_file():
        pytest.skip(f"no hlasm_export at {HLASM}; run `make hlasm`")
    root = tmp_path_factory.mktemp("carddemo")
    bms = load_bms_config(CONFIG)
    sym = root / "sym"
    generate(
        replace(
            bms,
            bms_dir=_here(bms.bms_dir),
            macros_dir=_here(bms.macros_dir),
            sym_dir=sym,
        )
    )
    corpus = load_corpus_config(CONFIG)
    asg = root / "asg"
    asg.mkdir()
    config = replace(
        corpus,
        cobol_dir=_here(corpus.cobol_dir),
        copybook_dirs=tuple(
            sym if path == bms.sym_dir else _here(path) for path in corpus.copybook_dirs
        ),
        asg_dir=asg,
    )
    jobs, _ = pending(config)
    dirs = tuple(str(path) for path in config.copybook_dirs)
    with ProcessPoolExecutor() as pool:
        results = tuple(
            pool.map(
                parse_one,
                jobs,
                [str(jar)] * len(jobs),
                [dirs] * len(jobs),
                [config.copybook_extensions] * len(jobs),
            )
        )
    assert {r.stem for r in results if not r.ok} == UNPARSED
    extents = root / "extents.jsonl"
    assert emit(asg, extents, (), ExtentsOptions(max_workers=4, undeclared=True)) == 0
    fixpoint = root / "fixpoint"
    cli(
        [
            "--asg-dir",
            str(asg),
            "--extents",
            str(extents),
            "--out-dir",
            str(fixpoint),
            "--all",
        ]
    )
    corpus_toml = root / "corpus.toml"
    corpus_toml.write_text(_toml(config), encoding="utf-8")
    out = root / "combine"
    assert (
        combine(
            [
                "--config",
                str(corpus_toml),
                "--fixpoint-dir",
                str(fixpoint),
                "--out-dir",
                str(out),
                "--all",
                "--max-hops",
                "5",
            ]
        )
        == 0
    )
    return CardDemoRun(
        extents=extents, fixpoint=fixpoint, combine=out, asg=asg, cobol=config.cobol_dir
    )
