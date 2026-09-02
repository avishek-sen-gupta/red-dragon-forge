"""Statement dispatch: a bridge statement type must map to a typed statement.

An unmapped type is a hard error that takes the whole program's ASG down
(parse_statement raises), so a type the bridge can emit needs an entry here.
"""

from cobol_asg.cobol_statements import (
    XmlGenerateStatement,
    parse_statement,
)


def test_xml_generate_parses() -> None:
    stmt = parse_statement(
        {
            "type": "XML_GENERATE",
            "xml_document": "WRITE-REC",
            "from_record": "SOME-RECORD",
        }
    )
    assert stmt == XmlGenerateStatement(
        xml_document="WRITE-REC", from_record="SOME-RECORD"
    )


def test_xml_generate_carries_count_and_exception_phrases() -> None:
    stmt = parse_statement(
        {
            "type": "XML_GENERATE",
            "xml_document": "WRITE-REC",
            "from_record": "SOME-RECORD",
            "count_in": "WS-XML-LEN",
            "on_exception": [
                {"type": "MOVE", "operands": ["'Y'", "WS-FAILED"]},
            ],
            "not_on_exception": [
                {"type": "MOVE", "operands": ["'N'", "WS-FAILED"]},
            ],
        }
    )
    assert isinstance(stmt, XmlGenerateStatement)
    assert stmt.count_in == "WS-XML-LEN"
    assert len(stmt.on_exception) == 1
    assert len(stmt.not_on_exception) == 1


def test_xml_generate_round_trips() -> None:
    data = {
        "type": "XML_GENERATE",
        "xml_document": "WRITE-REC",
        "from_record": "SOME-RECORD",
        "count_in": "WS-XML-LEN",
    }
    assert parse_statement(data).to_dict() == data
