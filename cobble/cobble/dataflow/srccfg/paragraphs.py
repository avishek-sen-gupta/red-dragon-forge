"""Paragraph order: the units a program's statements are grouped into, named.

Its own module so statements.py can ask for the order without reaching for
build.py, which now depends on the WHENEVER scope pass. That pass reads
statements, so leaving the order in build would close an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter

from cobble.dataflow.srccfg.synthetic import IMPLICIT_FIRST


@dataclass(frozen=True)
class ParagraphRef:
    name: str
    section: str
    statements: tuple


def label_id(name: str) -> str:
    return f"{name}#label"


def end_id(name: str) -> str:
    return f"{name}#end"


def paragraph_order(asg) -> tuple[ParagraphRef, ...]:
    """Declaration order, with a synthetic paragraph wherever statements belong to
    no paragraph -- division level, or the head of a section. That code executes,
    so it needs a name; the reserved prefix keeps the name from colliding.

    A duplicate paragraph name -- legal in COBOL when in different sections -- is
    renamed on later occurrences to keep node ids unique. The first occurrence keeps
    its name unchanged; later ones become {name}%{n} where n is 2, 3, and so on.
    Comparison is case-insensitive, matching how GO TO targets are upper-cased.
    """
    raw = (
        *_implicit(IMPLICIT_FIRST, "", asg.statements),
        *(ref for section in asg.sections for ref in _of_section(section)),
        *(_of_paragraph(paragraph, "") for paragraph in asg.paragraphs),
    )
    return _dedupe_names(raw)


def _dedupe_names(refs: tuple[ParagraphRef, ...]) -> tuple[ParagraphRef, ...]:
    """Rename duplicate paragraph names to keep node ids unique. A duplicate
    paragraph name is legal in COBOL when in different sections, but would produce
    duplicate node ids and a false graph."""
    occurrences = _occurrences(tuple(ref.name.upper() for ref in refs))
    return tuple(
        ParagraphRef(
            name=ref.name if occurrence == 1 else f"{ref.name}%{occurrence}",
            section=ref.section,
            statements=ref.statements,
        )
        for ref, occurrence in zip(refs, occurrences, strict=True)
    )


def _occurrences(names: tuple[str, ...]) -> tuple[int, ...]:
    """For each position, how many times its name has appeared up to and including
    it. Grouped by sorting rather than counted by recursion: a program can have
    thousands of paragraphs, and a walk that recursed once per paragraph died at a
    thousand."""
    by_name = sorted(zip(names, range(len(names)), strict=True))
    numbered = {
        at: occurrence
        for _, group in groupby(by_name, itemgetter(0))
        for occurrence, (_name, at) in enumerate(group, start=1)
    }
    return tuple(numbered[at] for at in range(len(names)))


def _of_section(section) -> tuple[ParagraphRef, ...]:
    return (
        *_implicit(f"{section.name}{IMPLICIT_FIRST}", section.name, section.statements),
        *(_of_paragraph(paragraph, section.name) for paragraph in section.paragraphs),
    )


def _implicit(name: str, section: str, statements) -> tuple[ParagraphRef, ...]:
    if not statements:
        return ()
    return (ParagraphRef(name=name, section=section, statements=tuple(statements)),)


def _of_paragraph(paragraph, section: str) -> ParagraphRef:
    return ParagraphRef(
        name=paragraph.name, section=section, statements=tuple(paragraph.statements)
    )
