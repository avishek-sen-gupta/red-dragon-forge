"""How a value the rules compare is spelled in a facts file."""

YES = "yes"
NO = "no"
ABSENT = "-"


def yes_no(flag: bool) -> str:
    return YES if flag else NO
