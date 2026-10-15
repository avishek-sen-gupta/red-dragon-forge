"""A CICS transaction: the transid a terminal enters and the program it starts."""

from dataclasses import dataclass

from litter.member_name import MemberName


@dataclass(frozen=True)
class Transaction:
    transid: str
    program: MemberName
