import json
import subprocess
import sys

from tests.covers import covers, NotLanguageFeature

SAMPLE_JSON = {
    "macro_invocations": [
        {
            "name": "DFHMSD",
            "label": "ORDERSET",
            "args": {"TYPE": "MAP", "LANG": "COBOL", "MODE": "INOUT", "TIOAPFX": "YES"},
            "range": {},
        },
        {
            "name": "DFHMDI",
            "label": "ORDERMAP",
            "args": {"SIZE": "(24,80)", "LINE": "1", "COLUMN": "1"},
            "range": {},
        },
        {
            "name": "DFHMDF",
            "label": "ORDNO",
            "args": {
                "LENGTH": "8",
                "POS": "(4,12)",
                "ATTRB": "(UNPROT,IC)",
                "PICOUT": "'99999999'",
            },
            "range": {},
        },
        {
            "name": "DFHMSD",
            "args": {"TYPE": "FINAL"},
            "range": {},
        },
    ]
}


def _run(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "bms_copybook_gen"] + args,
        input=stdin,
        capture_output=True,
        text=True,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_reads_json_file_and_emits_copybook(tmp_path):
    src = tmp_path / "map.json"
    src.write_text(json.dumps(SAMPLE_JSON))
    result = _run(["--input", str(src)])
    assert result.returncode == 0
    assert "01  ORDERMAPO" in result.stdout
    assert "ORDNOO" in result.stdout


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_reads_stdin():
    result = _run([], stdin=json.dumps(SAMPLE_JSON))
    assert result.returncode == 0
    assert "01  ORDERMAPO" in result.stdout


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_writes_to_output_file(tmp_path):
    src = tmp_path / "map.json"
    src.write_text(json.dumps(SAMPLE_JSON))
    out = tmp_path / "ORDERMAP.cpy"
    result = _run(["--input", str(src), "--output", str(out)])
    assert result.returncode == 0
    assert result.stdout == ""
    content = out.read_text()
    assert "01  ORDERMAPO" in content
    assert "ORDNOO" in content


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_input_map_present_for_inout(tmp_path):
    src = tmp_path / "map.json"
    src.write_text(json.dumps(SAMPLE_JSON))
    result = _run(["--input", str(src)])
    assert "ORDERMAPI REDEFINES ORDERMAPO" in result.stdout
    assert "ORDNOI" in result.stdout


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cli_missing_file_returns_nonzero():
    result = _run(["--input", "/nonexistent/path.json"])
    assert result.returncode != 0
