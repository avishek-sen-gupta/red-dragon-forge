"""The names this pass invents, and how to recognise one.

Some of what a member does has no field to hang a dependency on: a handler armed by
HANDLE CONDITION, the I-O outcome an AT END arm tests, the caller's parameter a CALL
aliases. Giving each of those a reserved name turns it into an ordinary write and an
ordinary read, so one reaching-definitions pass answers questions about it and there
is no second model to keep consistent. Nothing the source declares can collide: every
name here is ``%``-prefixed or carries a ``:``, and a COBOL data name can be neither.

The vocabulary lives here, once, for the same reason ``literals.py`` exists. It was
spelled independently in five modules -- ``%HANDLER[`` twice, in two of them -- and
the one module that has to RECOGNISE a synthetic name rather than construct it knew
about the ``:`` family and nothing about the ``%`` family. So ``%HANDLER[ANY]``
printed as a field the analysis had lost while the definition of it sat two nodes
away. A constructor with no matching classifier is how that happens, so the
classifier ships beside the constructors.

``DFHRESP(...)`` is here too. This pass builds that text for a CICS response
comparison, no member declares it, and without a classification it reached
``writers_of``, where ``base_field`` cut it back to ``DFHRESP`` and the report named
that as a field written nowhere.
"""

from __future__ import annotations

from dataclasses import dataclass

IMPLICIT_FIRST = "%MAIN"

HANDLER_PREFIX = "%HANDLER["
HANDLER_ANY = f"{HANDLER_PREFIX}ANY]"
RAISED = "RAISED"

IOSTATUS_PREFIX = "%IOSTATUS["
USING_PREFIX = "%USING["

IGNORED = "%IGNORE"
SYSTEM_DEFAULT = "%SYSTEM"

DFHRESP_PREFIX = "DFHRESP("

IDENTITY_PREFIXES = ("PROGRAM:", "FILE:", "MAP:", "TSQ:", "TRANSID:")

HANDLER = "HANDLER"
IOSTATUS = "IOSTATUS"
USING = "USING"
DISPOSITION = "DISPOSITION"
PARAGRAPH = "PARAGRAPH"
DFHRESP = "DFHRESP"


def handler_field(condition: str) -> str:
    """The synthetic field a HANDLE CONDITION assigns to.

    Arming a handler is a definition, not a jump: the transfer happens later, at
    whichever command raises. Modelling it this way means PUSH HANDLE, re-arming in
    a loop, and "which handler is live here" are all reaching definitions over this
    field, with no separate handler model to keep consistent.
    """
    return f"{HANDLER_PREFIX}{condition}]"


def io_status_field(subject: str) -> str:
    """The synthetic field an I-O arm tests.

    No field the program declares carries this, and naming the subject is what
    keeps two files' AT END arms -- or two computes' size errors -- distinct.
    """
    return f"{IOSTATUS_PREFIX}{subject}]"


def using_field(position: int) -> str:
    """The callee side of a CALL ... USING alias.

    A parameter's identity is its position, because the callee is free to name it
    anything, so the position is what the alias is keyed on.
    """
    return f"{USING_PREFIX}{position}]"


def dfhresp_operand(condition: str) -> str:
    return f"{DFHRESP_PREFIX}{condition})"


@dataclass(frozen=True)
class Synthetic:
    """What a synthetic name is, for a report that has to say so rather than guess.

    ``external`` splits the two families apart, and the split is the whole point of
    the classification. An identity name (``PROGRAM:``, ``FILE:``, ``DFHRESP(``)
    names something real that lives outside this member, so "written nowhere in this
    member" is true of it but useless. A ``%`` name is state this pass invented to
    model control flow, so "written nowhere" is not even true -- something wrote it,
    under a name the reader never typed.
    """

    name: str = ""
    kind: str = ""
    subject: str = ""
    external: bool = False

    def __bool__(self) -> bool:
        """Falsy for ``NOT_SYNTHETIC``, so a caller can ask and act in one step.

        A sentinel rather than ``None``: an absent classification has exactly one
        meaning here -- "ask the member about this name" -- and there is nothing for
        a caller to unwrap.
        """
        return bool(self.kind)


NOT_SYNTHETIC = Synthetic()

_BRACKETED = (
    (HANDLER, HANDLER_PREFIX),
    (IOSTATUS, IOSTATUS_PREFIX),
    (USING, USING_PREFIX),
)


def is_synthetic(name: str) -> Synthetic:
    """The classification of a name this pass invented, ``NOT_SYNTHETIC`` otherwise.

    A falsy answer means "ask the member about it". Every other answer means a report
    must not send the name to ``writers_of`` and print the empty result as a finding.
    """
    identity = next((p for p in IDENTITY_PREFIXES if name.startswith(p)), None)
    if identity:
        return Synthetic(
            name=name,
            kind=identity.removesuffix(":"),
            subject=name.removeprefix(identity),
            external=True,
        )
    if name.startswith(DFHRESP_PREFIX) and name.endswith(")"):
        return Synthetic(
            name=name,
            kind=DFHRESP,
            subject=name.removeprefix(DFHRESP_PREFIX).removesuffix(")"),
            external=True,
        )
    return _invented(name)


def _invented(name: str) -> Synthetic:
    bracketed = next(
        (
            entry
            for entry in _BRACKETED
            if name.startswith(entry[1]) and name.endswith("]")
        ),
        None,
    )
    if bracketed:
        return Synthetic(
            name=name,
            kind=bracketed[0],
            subject=name.removeprefix(bracketed[1]).removesuffix("]"),
        )
    if name in (IGNORED, SYSTEM_DEFAULT):
        return Synthetic(name=name, kind=DISPOSITION)
    if name.endswith(IMPLICIT_FIRST):
        return Synthetic(
            name=name, kind=PARAGRAPH, subject=name.removesuffix(IMPLICIT_FIRST)
        )
    return NOT_SYNTHETIC


def describe(item: Synthetic) -> str:
    """One phrase a report prints in place of "written nowhere in this member"."""
    if item.external:
        return f"external identifier ({item.kind})"
    return f"synthetic ({_INVENTED[item.kind](item.subject)})"


_INVENTED = {
    HANDLER: lambda subject: f"the handler armed for {subject or 'a condition'}",
    IOSTATUS: lambda subject: f"the I-O outcome of {subject or 'a statement'}",
    USING: lambda subject: f"the caller's parameter at position {subject}",
    DISPOSITION: lambda _: "a handler disposition, not a paragraph",
    PARAGRAPH: lambda subject: f"the implicit paragraph of {subject or 'the program'}",
}
