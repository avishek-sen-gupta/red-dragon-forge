# pyright: standard
"""Unit tests for tools/mainframe_inventory.py — the usage-surface inventory.

The script is standalone (stdlib only, no repo imports), so it is loaded off
tools/ via sys.path rather than imported as a workspace package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

from mainframe_inventory import (  # noqa: E402
    build_inventory,
    format_report,
    jcl_lines,
    scan_text,
)


class TestJclCardFormat:
    """JCL is card-formatted: cols 73-80 are sequence numbers, //* is a comment,
    and a trailing comma continues the statement onto the next card."""

    def test_strips_sequence_numbers_in_columns_73_to_80(self):
        card = "//STEP01 EXEC PGM=IDCAMS".ljust(72) + "SEQ00010"
        assert jcl_lines(card) == ["//STEP01 EXEC PGM=IDCAMS"]

    def test_drops_comment_cards(self):
        text = "//*  DELETE THE VSAM FILE\n//STEP01 EXEC PGM=IDCAMS\n"
        assert jcl_lines(text) == ["//STEP01 EXEC PGM=IDCAMS"]

    def test_joins_a_continued_statement_into_one_logical_line(self):
        text = "//DD1 DD DISP=SHR,\n//         DSN=AWS.M2.CARDDEMO.ACCTDATA\n"
        assert jcl_lines(text) == ["//DD1 DD DISP=SHR,DSN=AWS.M2.CARDDEMO.ACCTDATA"]

    def test_keeps_in_stream_deck_content_verbatim(self):
        """SYSIN payload is not JCL: a trailing comma is the utility's own
        syntax and must not trigger JCL continuation joining."""
        text = "//SYSIN DD *\n  SORT FIELDS=(1,4,CH,A),\n  SKIPREC=2\n/*\n"
        assert jcl_lines(text) == [
            "//SYSIN DD *",
            "  SORT FIELDS=(1,4,CH,A),",
            "  SKIPREC=2",
            "/*",
        ]


class TestJclStatements:
    def test_counts_statement_kinds(self):
        text = (
            "//RUNJOB JOB 'x',CLASS=A\n//S1 EXEC PGM=IDCAMS\n//SYSPRINT DD SYSOUT=*\n"
        )
        found = scan_text(text)
        assert found["JCL.STMT.JOB"] == 1
        assert found["JCL.STMT.EXEC"] == 1
        assert found["JCL.STMT.DD"] == 1

    def test_detects_jes2_control_cards(self):
        assert scan_text("/*JOBPARM SYSAFF=ANY\n")["JCL.JES.JOBPARM"] == 1


class TestJclParameters:
    def test_records_each_disp_subparameter_separately(self):
        found = scan_text("//D1 DD DISP=(NEW,CATLG,DELETE),DSN=A.B\n")
        assert found["JCL.PARM.DISP"] == 1
        assert found["JCL.PARM.DISP.NEW"] == 1
        assert found["JCL.PARM.DISP.CATLG"] == 1
        assert found["JCL.PARM.DISP.DELETE"] == 1

    def test_detects_vsam_buffering_and_sms_class_parameters(self):
        """AMP and the SMS classes are surface-area tells a naive scan misses."""
        text = "//D1 DD DSN=A.B,AMP=('BUFND=10'),STORCLAS=SCBASE,DATACLAS=DCVSAM\n"
        found = scan_text(text)
        assert found["JCL.PARM.AMP"] == 1
        assert found["JCL.PARM.STORCLAS"] == 1
        assert found["JCL.PARM.DATACLAS"] == 1

    def test_detects_uss_path_dd(self):
        found = scan_text("//STDOUT DD PATH='/tmp/out.txt',PATHOPTS=(OWRONLY)\n")
        assert found["JCL.PARM.PATH"] == 1


class TestDsnShapes:
    def test_detects_relative_and_absolute_gdg_references(self):
        text = "//D1 DD DSN=A.B.C(+1)\n//D2 DD DSN=A.B.C.G0004V00\n"
        found = scan_text(text)
        assert found["JCL.DSN.GDG_RELATIVE"] == 1
        assert found["JCL.DSN.GDG_ABSOLUTE"] == 1

    def test_detects_pds_member_reference(self):
        assert scan_text("//D1 DD DSN=MY.PROCLIB(MEMBER1)\n")["JCL.DSN.PDS_MEMBER"] == 1

    def test_does_not_confuse_a_gdg_reference_for_a_pds_member(self):
        found = scan_text("//D1 DD DSN=A.B.C(+1)\n")
        assert found["JCL.DSN.PDS_MEMBER"] == 0

    def test_detects_temp_dataset_and_backward_reference(self):
        text = "//D1 DD DSN=&&TEMP1\n//D2 DD DSN=*.STEP01.OUTDD\n"
        found = scan_text(text)
        assert found["JCL.DSN.TEMP"] == 1
        assert found["JCL.DSN.REFERBACK"] == 1

    def test_detects_dd_concatenation(self):
        text = "//STEPLIB DD DSN=MY.LOADLIB\n//         DD DSN=OTHER.LOADLIB\n"
        assert scan_text(text)["JCL.DD.CONCATENATION"] == 1

    def test_detects_system_symbols_distinctly_from_user_symbols(self):
        text = "//J JOB NOTIFY=&SYSUID\n//D1 DD DSN=&HLQ..DATA\n"
        found = scan_text(text)
        assert found["JCL.SYMBOL.SYSTEM.SYSUID"] == 1
        assert found["JCL.SYMBOL.USER"] == 1


class TestToolCensus:
    def test_counts_each_invoked_program(self):
        text = "//S1 EXEC PGM=IDCAMS\n//S2 EXEC PGM=SORT\n//S3 EXEC PGM=IDCAMS\n"
        found = scan_text(text)
        assert found["TOOL.IDCAMS"] == 2
        assert found["TOOL.SORT"] == 1

    def test_counts_a_proc_invocation_distinctly_from_a_program(self):
        found = scan_text("//S1 EXEC PROC=MYPROC\n//S2 EXEC OTHERPRC\n")
        assert found["PROC.MYPROC"] == 1
        assert found["PROC.OTHERPRC"] == 1

    def test_splits_parm_into_individual_options(self):
        """For compilers the whole surface lives in PARM, so tokenize it."""
        found = scan_text("//C EXEC PGM=IGYCRCTL,PARM='RENT,APOST,LIB'\n")
        assert found["TOOL.IGYCRCTL.PARM.RENT"] == 1
        assert found["TOOL.IGYCRCTL.PARM.APOST"] == 1
        assert found["TOOL.IGYCRCTL.PARM.LIB"] == 1

    def test_captures_positional_parm_of_an_ims_region_controller(self):
        found = scan_text("//S EXEC PGM=DFSRRC00,PARM=(DLI,CBLPGM,PSBNAME)\n")
        assert found["TOOL.DFSRRC00.PARM.DLI"] == 1
        assert found["TOOL.DFSRRC00.PARM.CBLPGM"] == 1


class TestControlDecks:
    def test_attributes_a_sysin_verb_to_the_enclosing_tool(self):
        text = "//S1 EXEC PGM=IDCAMS\n//SYSIN DD *\n  REPRO INFILE(A) OUTFILE(B)\n/*\n"
        assert scan_text(text)["TOOL.IDCAMS.REPRO"] == 1

    def test_recognises_a_two_word_verb_and_its_operand_keywords(self):
        text = (
            "//S1 EXEC PGM=IDCAMS\n"
            "//SYSIN DD *\n"
            "  DEFINE CLUSTER (NAME(A.B) KEYS(16 0) SHAREOPTIONS(2 3) ERASE)\n"
            "/*\n"
        )
        found = scan_text(text)
        assert found["TOOL.IDCAMS.DEFINE_CLUSTER"] == 1
        assert found["TOOL.IDCAMS.DEFINE_CLUSTER.SHAREOPTIONS"] == 1
        assert found["TOOL.IDCAMS.DEFINE_CLUSTER.KEYS"] == 1

    def test_reads_icetool_control_statements_from_toolin_not_sysin(self):
        text = "//S1 EXEC PGM=ICETOOL\n//TOOLIN DD *\n  OCCUR FROM(IN) LIST(OUT)\n/*\n"
        assert scan_text(text)["TOOL.ICETOOL.OCCUR"] == 1

    def test_reads_tso_commands_from_systsin_and_follows_nested_db2_subcommands(self):
        text = (
            "//S1 EXEC PGM=IKJEFT01\n"
            "//SYSTSIN DD *\n"
            "  DSN SYSTEM(DB2P)\n"
            "  RUN PROGRAM(MYPGM) PLAN(MYPLAN) LIB('MY.LOAD')\n"
            "  END\n"
            "/*\n"
        )
        found = scan_text(text)
        assert found["TOOL.IKJEFT01.DSN"] == 1
        assert found["TOOL.IKJEFT01.DSN.RUN_PROGRAM"] == 1

    def test_recognises_iebupdte_control_cards(self):
        text = "//S1 EXEC PGM=IEBUPDTE\n//SYSIN DD DATA\n./ ADD NAME=MEMBER1\n/*\n"
        assert scan_text(text)["TOOL.IEBUPDTE.ADD"] == 1

    def test_attributes_each_deck_to_its_own_step(self):
        text = (
            "//S1 EXEC PGM=IDCAMS\n//SYSIN DD *\n  LISTCAT ENTRIES(A.B)\n/*\n"
            "//S2 EXEC PGM=SORT\n//SYSIN DD *\n  SORT FIELDS=(1,16,CH,A)\n/*\n"
        )
        found = scan_text(text)
        assert found["TOOL.IDCAMS.LISTCAT"] == 1
        assert found["TOOL.SORT.SORT"] == 1
        assert found["TOOL.SORT.LISTCAT"] == 0


class TestUnknownToolProfiling:
    """An unregistered tool must self-report, not vanish — this is how a weird
    vendor utility gets discovered instead of silently shrinking the surface."""

    def test_flags_the_tool_as_unregistered_and_fingerprints_its_dds(self):
        text = (
            "//S1 EXEC PGM=ACMEUTIL\n"
            "//SYSUT1 DD DSN=A.B\n"
            "//ACMECTL DD *\n"
            "  FROBNICATE LEVEL(3)\n"
            "/*\n"
        )
        found = scan_text(text)
        assert found["TOOL.ACMEUTIL.UNREGISTERED"] == 1
        assert found["TOOL.ACMEUTIL.DD.SYSUT1"] == 1
        assert found["TOOL.ACMEUTIL.DD.ACMECTL"] == 1
        assert found["TOOL.ACMEUTIL.DECK.FROBNICATE"] == 1

    def test_does_not_fingerprint_dds_of_a_registered_tool(self):
        found = scan_text("//S1 EXEC PGM=IDCAMS\n//SYSPRINT DD SYSOUT=*\n")
        assert found["TOOL.IDCAMS.UNREGISTERED"] == 0
        assert found["TOOL.IDCAMS.DD.SYSPRINT"] == 0


class TestCicsVerbs:
    def test_joins_a_command_spanning_several_lines(self):
        text = (
            "           EXEC CICS READ\n"
            "                FILE('ACCTDAT')\n"
            "                RIDFLD(WS-ACCT-ID)\n"
            "                INTO(ACCT-RECORD)\n"
            "           END-EXEC.\n"
        )
        found = scan_text(text)
        assert found["CICS.READ"] == 1
        assert found["CICS.READ.FILE"] == 1
        assert found["CICS.READ.RIDFLD"] == 1

    def test_distinguishes_send_map_from_send_text(self):
        text = (
            "      EXEC CICS SEND MAP('M1') MAPSET('S1') END-EXEC.\n"
            "      EXEC CICS SEND TEXT FROM(WS-MSG) END-EXEC.\n"
        )
        found = scan_text(text)
        assert found["CICS.SEND_MAP"] == 1
        assert found["CICS.SEND_TEXT"] == 1
        assert found["CICS.SEND_MAP.MAPSET"] == 1

    def test_skips_a_cobol_comment_line(self):
        text = "000100* EXEC CICS SYNCPOINT END-EXEC.\n"
        assert scan_text(text)["CICS.SYNCPOINT"] == 0

    def test_classifies_verbs_into_functional_areas(self):
        text = (
            "      EXEC CICS WRITEQ TS QUEUE('Q1') FROM(W) END-EXEC.\n"
            "      EXEC CICS GETMAIN SET(PTR) LENGTH(100) END-EXEC.\n"
            "      EXEC CICS LINK PROGRAM('P1') END-EXEC.\n"
        )
        found = scan_text(text)
        assert found["CICS.AREA.TEMP_STORAGE"] == 1
        assert found["CICS.AREA.STORAGE"] == 1
        assert found["CICS.AREA.PROGRAM_CONTROL"] == 1

    def test_detects_function_shipping_via_sysid(self):
        """SYSID means the resource lives in another region — a surface-area tell."""
        text = "      EXEC CICS READ FILE('F') SYSID('CICB') RIDFLD(K) END-EXEC.\n"
        assert scan_text(text)["CICS.READ.SYSID"] == 1

    def test_detects_channel_and_container_commands(self):
        text = "      EXEC CICS PUT CONTAINER('C1') CHANNEL('CH') FROM(W) END-EXEC.\n"
        found = scan_text(text)
        assert found["CICS.PUT_CONTAINER"] == 1
        assert found["CICS.AREA.CHANNEL"] == 1

    def test_detects_condition_handling(self):
        text = "      EXEC CICS HANDLE CONDITION NOTFND(NO-REC) END-EXEC.\n"
        assert scan_text(text)["CICS.HANDLE_CONDITION"] == 1


class TestEmbeddedLanguages:
    def test_detects_embedded_sql_verbs(self):
        text = (
            "      EXEC SQL DECLARE C1 CURSOR FOR SELECT A FROM T END-EXEC.\n"
            "      EXEC SQL FETCH C1 INTO :WS-A END-EXEC.\n"
        )
        found = scan_text(text)
        assert found["SQL.DECLARE"] == 1
        assert found["SQL.FETCH"] == 1

    def test_detects_bms_macros(self):
        text = (
            "MAP1     DFHMSD TYPE=MAP,MODE=INOUT,LANG=COBOL\n"
            "SCRN     DFHMDI SIZE=(24,80)\n"
            "FLD1     DFHMDF POS=(1,1),LENGTH=8,ATTRB=(PROT)\n"
        )
        found = scan_text(text)
        assert found["BMS.DFHMSD"] == 1
        assert found["BMS.DFHMDI"] == 1
        assert found["BMS.DFHMDF"] == 1


class TestFileDiscovery:
    """Extensions are not trusted: real corpora keep JCL in extensionless
    PROCLIB members, .txt copies, and anything else. Scan everything."""

    def test_scans_files_regardless_of_extension(self, tmp_path):
        (tmp_path / "PROCMEM").write_text("//S1 EXEC PGM=IDCAMS\n")
        (tmp_path / "notes.txt").write_text("//S2 EXEC PGM=SORT\n")
        inv = build_inventory([tmp_path])
        assert inv.counts["TOOL.IDCAMS"] == 1
        assert inv.counts["TOOL.SORT"] == 1

    def test_recurses_into_subdirectories(self, tmp_path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "deep.jcl").write_text("//S1 EXEC PGM=IDCAMS\n")
        assert build_inventory([tmp_path]).counts["TOOL.IDCAMS"] == 1

    def test_skips_vcs_and_build_directories(self, tmp_path):
        junk = tmp_path / ".git"
        junk.mkdir()
        (junk / "x.jcl").write_text("//S1 EXEC PGM=IDCAMS\n")
        assert build_inventory([tmp_path]).counts["TOOL.IDCAMS"] == 0

    def test_skips_binary_files_without_raising(self, tmp_path):
        (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02PGM=IDCAMS\x00")
        assert build_inventory([tmp_path]).counts["TOOL.IDCAMS"] == 0

    def test_tracks_how_many_distinct_files_use_a_feature(self, tmp_path):
        (tmp_path / "one.jcl").write_text(
            "//S1 EXEC PGM=IDCAMS\n//S2 EXEC PGM=IDCAMS\n"
        )
        (tmp_path / "two.jcl").write_text("//S1 EXEC PGM=IDCAMS\n")
        inv = build_inventory([tmp_path])
        assert inv.counts["TOOL.IDCAMS"] == 3
        assert len(inv.files["TOOL.IDCAMS"]) == 2


class TestReport:
    def test_orders_by_count_then_name_for_stable_diffs(self, tmp_path):
        (tmp_path / "a.jcl").write_text("//S1 EXEC PGM=SORT\n//S2 EXEC PGM=SORT\n")
        (tmp_path / "b.jcl").write_text("//S1 EXEC PGM=IDCAMS\n")
        lines = format_report(build_inventory([tmp_path])).splitlines()
        tools = [ln.split()[0] for ln in lines if ln.startswith("TOOL.")]
        assert tools.index("TOOL.SORT") < tools.index("TOOL.IDCAMS")

    def test_can_filter_to_a_single_category(self, tmp_path):
        (tmp_path / "a.jcl").write_text("//S1 EXEC PGM=SORT\n")
        report = format_report(build_inventory([tmp_path]), category="TOOL")
        assert "TOOL.SORT" in report
        assert "JCL.STMT.EXEC" not in report


class TestMultiWordVerbsDeclaredAcrossSourceLines:
    """The two-word verb tables are written as wrapped |-separated literals;
    entries after a line break must still match."""

    def test_recognises_define_generationdatagroup(self):
        text = (
            "//S1 EXEC PGM=IDCAMS\n"
            "//SYSIN DD *\n"
            "  DEFINE GENERATIONDATAGROUP (NAME(A.B) LIMIT(5) NOEMPTY SCRATCH)\n"
            "/*\n"
        )
        found = scan_text(text)
        assert found["TOOL.IDCAMS.DEFINE_GENERATIONDATAGROUP"] == 1
        assert found["TOOL.IDCAMS.DEFINE_GENERATIONDATAGROUP.LIMIT"] == 1

    def test_recognises_cics_put_container(self):
        text = "      EXEC CICS PUT CONTAINER('C1') FROM(W) END-EXEC.\n"
        assert scan_text(text)["CICS.PUT_CONTAINER"] == 1

    def test_recognises_csdup_define_program(self):
        text = (
            "//S1 EXEC PGM=DFHCSDUP\n//SYSIN DD *\n  DEFINE PROGRAM(P1) GROUP(G1)\n/*\n"
        )
        assert scan_text(text)["TOOL.DFHCSDUP.DEFINE_PROGRAM"] == 1


class TestTranslatorsAreRegisteredTools:
    """Precompilers/translators are tools, not application programs — the
    unregistered bucket surfaced these two when run against CardDemo."""

    def test_db2_precompiler_is_registered(self):
        assert scan_text("//S EXEC PGM=DSNHPC\n")["TOOL.DSNHPC.UNREGISTERED"] == 0

    def test_cics_translator_is_registered(self):
        assert scan_text("//S EXEC PGM=DFHECP1$\n")["TOOL.DFHECP1$.UNREGISTERED"] == 0
