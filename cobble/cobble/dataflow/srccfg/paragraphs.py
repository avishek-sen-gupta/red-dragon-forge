"""Paragraph order: the units a program's statements are grouped into, named.

Its own module so statements.py can ask for the order without reaching for
build.py, which now depends on the WHENEVER scope pass. That pass reads
statements, so leaving the order in build would close an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import groupby
from operator import itemgetter

from cobble.dataflow.srccfg.synthetic import IMPLICIT_FIRST


@dataclass(frozen=True)
class ParagraphRef:
    name: str
    section: str
    statements: tuple
    sentence_ends: tuple[int, ...] = ()


def label_id(name: str) -> str:
    return f"{name}#label"


def end_id(name: str) -> str:
    return f"{name}#end"


def sentence_end_id(name: str, position: int) -> str:
    return f"{name}#sentence.{position}"


def paragraph_order(asg) -> tuple[ParagraphRef, ...]:
    """Declaration order, with a synthetic paragraph wherever statements belong to
    no paragraph -- division level, or the head of a section. That code executes,
    so it needs a name; the reserved prefix keeps the name from colliding.

    A duplicate paragraph name -- legal in COBOL when in different sections -- is
    renamed on later occurrences to keep node ids unique. The first occurrence keeps
    its name unchanged; later ones become {name}%{n} where n is 2, 3, and so on.

    Names are upper-cased here, once. COBOL names are case-insensitive and every
    jump target is upper-cased where it is lowered, so a name kept in its declared
    spelling is a label no jump to it resolves to.
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
    occurrences = _occurrences(tuple(ref.name for ref in refs))
    return tuple(
        replace(ref, name=ref.name if occurrence == 1 else f"{ref.name}%{occurrence}")
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
    name = section.name.upper()
    return (
        *_implicit(f"{name}{IMPLICIT_FIRST}", name, section.statements),
        *(_of_paragraph(paragraph, name) for paragraph in section.paragraphs),
    )


def _implicit(name: str, section: str, statements) -> tuple[ParagraphRef, ...]:
    if not statements:
        return ()
    return (ParagraphRef(name=name, section=section, statements=tuple(statements)),)


def _of_paragraph(paragraph, section: str) -> ParagraphRef:
    return ParagraphRef(
        name=paragraph.name.upper(),
        section=section,
        statements=tuple(paragraph.statements),
        sentence_ends=tuple(paragraph.sentence_ends),
    )
