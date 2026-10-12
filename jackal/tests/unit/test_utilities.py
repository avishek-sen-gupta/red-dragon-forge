from jackal.allocation import DdEnvironment
from jackal.model import ProgramRef
from jackal.utilities import UTILITIES
from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, disp, program
from tests.system_build import job_catalog


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_iefbr14_does_nothing_itself_since_the_runner_allocates_and_disposes(
    tmp_path,
):
    cat = job_catalog(tmp_path)
    step = program("DEL", "IEFBR14", (dd("D", "J.TMP", disp("NEW", "DELETE")),))
    assert (
        UTILITIES[ProgramRef("IEFBR14")](step, DdEnvironment(()), cat),
        [f for f in tmp_path.rglob("*") if f.is_file()],
    ) == (0, [])


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_idcams_reads_each_sysin_record_between_columns_2_and_72(tmp_path):
    """AMS p. xxiv: for batch jobs the default margins are 2 and 72, so column 1
    and a sequence number in columns 73-80 are not part of the command."""
    from jackal.gdg import Empty, GdgBase, GdgOrder, Scratch
    from jackal.model import DD, DdName, InStreamDSN, NotCoded

    cat = job_catalog(tmp_path)
    sysin = DD(
        DdName("SYSIN"),
        InStreamDSN(),
        NotCoded(),
        in_stream=(
            "*  DEFINE GENERATIONDATAGROUP -".ljust(72) + "00010000",
            "     (NAME(A.B.HIST) LIMIT(3))".ljust(72) + "00020000",
        ),
    )
    step = program("DEF", "IDCAMS", (sysin,))
    assert UTILITIES[ProgramRef("IDCAMS")](step, DdEnvironment(()), cat) == 0
    assert cat.gdg("A.B.HIST") == GdgBase(
        "A.B.HIST", 3, Empty.NOEMPTY, Scratch.NOSCRATCH, GdgOrder.LIFO, ()
    )
