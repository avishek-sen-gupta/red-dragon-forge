"""Shared types for cobble.viz pipeline artifacts."""

from __future__ import annotations

from pydantic import BaseModel

# ── Call Dependency ──────────────────────────────────────────────────────────


class CallEdge(BaseModel, frozen=True):
    from_program: str
    to_program: str
    paragraph: str
    commarea: str = ""


class ProgramNode(BaseModel, frozen=True):
    program: str
    heading: str = ""  # filled by cobol-viz-summarize
    summary: str = ""  # filled by cobol-viz-summarize
    calls: tuple[str, ...] = ()
    called_by: tuple[str, ...] = ()


class CallDepGraph(BaseModel, frozen=True):
    entry: str
    nodes: tuple[ProgramNode, ...]
    edges: tuple[CallEdge, ...]


# ── Sequence ─────────────────────────────────────────────────────────────────


class CrossProgramCall(BaseModel, frozen=True):
    """One inter-program call in execution order."""

    from_program: str
    to_program: str
    via_paragraph: str  # paragraph in from_program that issues the LINK


class CrossProgramSequence(BaseModel, frozen=True):
    """Top-level: ordered list of all cross-program LINK calls from entry."""

    entry: str
    calls: tuple[CrossProgramCall, ...]


class Arm(BaseModel, frozen=True):
    """One arm of a decision a step runs inside.

    ``decision`` names the IF or EVALUATE statement, so steps sharing it are
    alternatives of one choice; ``arm`` names which branch (``then``, ``else``,
    ``when.<n>``) and ``label`` is how the diagram shows it.
    """

    decision: str
    arm: str
    label: str


class SequenceStep(BaseModel, frozen=True):
    """One PERFORM site in a single program's internal PERFORM tree."""

    type: str  # "perform" | "link"
    paragraph: str
    callee_program: str = ""  # set when type=="link"; no recursion
    has_decision: bool = False
    call_type: str = "simple"  # "simple" | "loop" | "conditional" | "conditional_loop"
    arms: tuple[Arm, ...] = ()  # outermost first; empty when unconditional
    summary: str = ""  # filled by cobol-viz-summarize
    children: tuple[SequenceStep, ...] = ()


SequenceStep.model_rebuild()


class ProgramSequence(BaseModel, frozen=True):
    """Per-program: intra-program PERFORM tree; LINK calls are leaf markers."""

    program: str
    entry_paragraph: str = ""
    heading: str = ""  # filled by cobol-viz-summarize
    summary: str = ""  # filled by cobol-viz-summarize
    steps: tuple[SequenceStep, ...]


class SequenceOutput(BaseModel, frozen=True):
    """Combined output of cobol-viz-sequence."""

    cross_program: CrossProgramSequence
    per_program: dict[str, ProgramSequence]
