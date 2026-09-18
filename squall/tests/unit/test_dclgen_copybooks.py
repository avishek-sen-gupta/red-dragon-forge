"""Tests for squall.dclgen_copybooks — staging sanitised DCLGEN copybooks."""

from squall.dclgen_copybooks import stage_sanitised_copybooks

_DCLGEN = """\
      ******************************************************************
           EXEC SQL DECLARE CARDDEMO.TRANSACTION_TYPE TABLE
           ( TR_TYPE                        CHAR(2) NOT NULL,
             TR_DESCRIPTION                 VARCHAR(50) NOT NULL
           ) END-EXEC.
      ******************************************************************
       01  DCLTRANSACTION-TYPE.
           10 DCL-TR-TYPE          PIC X(2).
"""

_DCLGEN_WITH_CURSOR = """\
      ******************************************************************
           EXEC SQL DECLARE CARDDEMO.TRANSACTION_TYPE TABLE
           ( TR_TYPE                        CHAR(2) NOT NULL,
             TR_DESCRIPTION                 VARCHAR(50) NOT NULL
           ) END-EXEC.
      ******************************************************************
       01  DCLTRANSACTION-TYPE.
           10 DCL-TR-TYPE          PIC X(2).
       EXEC SQL DECLARE TRTYP-CURSOR CURSOR FOR
           SELECT TR_TYPE, TR_DESCRIPTION
             FROM CARDDEMO.TRANSACTION_TYPE
            WHERE TR_TYPE = :DCL-TR-TYPE
       END-EXEC.
"""

# Adversarial ordering: the cursor comes FIRST, and its own body contains the
# bare word TABLE (as a quoted literal) before its own END-EXEC. A regex that
# starts matching at the first "EXEC SQL DECLARE" and stops at the first
# bare TABLE / END-EXEC it meets — rather than requiring TABLE to follow
# immediately after the declared name — lands both inside the cursor's own
# body and deletes the whole cursor statement.
_DCLGEN_CURSOR_FIRST_ADVERSARIAL = """\
       EXEC SQL DECLARE TRTYP-CURSOR CURSOR FOR
           SELECT TR_TYPE, TR_DESCRIPTION
             FROM CARDDEMO.TRANSACTION_TYPE
            WHERE OBJTYPE = 'TABLE'
              AND TR_TYPE = :DCL-TR-TYPE
       END-EXEC.
      ******************************************************************
           EXEC SQL DECLARE CARDDEMO.TRANSACTION_TYPE TABLE
           ( TR_TYPE                        CHAR(2) NOT NULL,
             TR_DESCRIPTION                 VARCHAR(50) NOT NULL
           ) END-EXEC.
      ******************************************************************
       01  DCLTRANSACTION-TYPE.
           10 DCL-TR-TYPE          PIC X(2).
"""


def test_declare_table_block_is_removed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "DCLTRTYP.dcl").write_text(_DCLGEN, encoding="utf-8")

    out = stage_sanitised_copybooks([src], tmp_path / "out")

    staged = (out / "DCLTRTYP.dcl").read_text(encoding="utf-8")
    assert "DECLARE" not in staged
    assert "END-EXEC" not in staged


def test_host_variable_declarations_survive(tmp_path):
    """The whole point of the copybook is the 01 record — stripping must not
    reach past the DECLARE TABLE block."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "DCLTRTYP.dcl").write_text(_DCLGEN, encoding="utf-8")

    out = stage_sanitised_copybooks([src], tmp_path / "out")

    staged = (out / "DCLTRTYP.dcl").read_text(encoding="utf-8")
    assert "01  DCLTRANSACTION-TYPE." in staged
    assert "10 DCL-TR-TYPE          PIC X(2)." in staged


def test_copybooks_without_declare_table_are_copied_unchanged(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    plain = "       01  SOME-RECORD.\n           10 A PIC X.\n"
    (src / "PLAIN.cpy").write_text(plain, encoding="utf-8")

    out = stage_sanitised_copybooks([src], tmp_path / "out")

    assert (out / "PLAIN.cpy").read_text(encoding="utf-8") == plain


def test_earlier_source_dirs_win(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "D.dcl").write_text("       01  FROM-FIRST.\n", encoding="utf-8")
    (second / "D.dcl").write_text("       01  FROM-SECOND.\n", encoding="utf-8")

    out = stage_sanitised_copybooks([first, second], tmp_path / "out")

    assert "FROM-FIRST" in (out / "D.dcl").read_text(encoding="utf-8")


def test_declare_cursor_is_not_removed(tmp_path):
    """A DECLARE ... CURSOR is a real executable statement, not a
    precompiler-only declaration — it must survive verbatim, even alongside a
    DECLARE ... TABLE block that must be stripped."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "DCLTRTYP.dcl").write_text(_DCLGEN_WITH_CURSOR, encoding="utf-8")

    out = stage_sanitised_copybooks([src], tmp_path / "out")

    staged = (out / "DCLTRTYP.dcl").read_text(encoding="utf-8")
    assert "DECLARE TRTYP-CURSOR CURSOR FOR" in staged
    assert "SELECT TR_TYPE, TR_DESCRIPTION" in staged
    assert "FROM CARDDEMO.TRANSACTION_TYPE" in staged
    assert "WHERE TR_TYPE = :DCL-TR-TYPE" in staged
    assert staged.count("END-EXEC") == 1
    assert "DECLARE CARDDEMO.TRANSACTION_TYPE TABLE" not in staged


def test_declare_cursor_survives_when_it_precedes_declare_table(tmp_path):
    """Adversarial ordering: the cursor comes first and its own body contains
    a bare TABLE token before its own END-EXEC. Stripping must anchor on the
    declared-name-then-TABLE adjacency (Db2's actual DECLARE TABLE syntax),
    not on any bare TABLE/END-EXEC reachable from the first EXEC SQL DECLARE
    — otherwise the whole cursor statement, real executable SQL, is deleted."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "DCLTRTYP.dcl").write_text(
        _DCLGEN_CURSOR_FIRST_ADVERSARIAL, encoding="utf-8"
    )

    out = stage_sanitised_copybooks([src], tmp_path / "out")

    staged = (out / "DCLTRTYP.dcl").read_text(encoding="utf-8")
    assert "DECLARE TRTYP-CURSOR CURSOR FOR" in staged
    assert "SELECT TR_TYPE, TR_DESCRIPTION" in staged
    assert "WHERE OBJTYPE = 'TABLE'" in staged
    assert "AND TR_TYPE = :DCL-TR-TYPE" in staged
    assert staged.count("END-EXEC") == 1
    assert "DECLARE CARDDEMO.TRANSACTION_TYPE TABLE" not in staged
    assert "01  DCLTRANSACTION-TYPE." in staged


def test_restaging_overwrites_stale_output(tmp_path):
    """A stale file left in out_dir from an earlier call must never silently
    shadow a real copybook — every call writes fresh content, even when the
    filename was already staged."""
    src = tmp_path / "src"
    src.mkdir()
    out_dir = tmp_path / "out"
    (src / "D.dcl").write_text("       01  FIRST-VERSION.\n", encoding="utf-8")

    stage_sanitised_copybooks([src], out_dir)
    (src / "D.dcl").write_text("       01  SECOND-VERSION.\n", encoding="utf-8")
    stage_sanitised_copybooks([src], out_dir)

    staged = (out_dir / "D.dcl").read_text(encoding="utf-8")
    assert "SECOND-VERSION" in staged
    assert "FIRST-VERSION" not in staged
