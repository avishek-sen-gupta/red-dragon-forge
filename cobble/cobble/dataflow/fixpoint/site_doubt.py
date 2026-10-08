"""Why a dynamic site stayed unresolved, when the reason is not one its values carry."""

from enum import StrEnum


class SiteDoubt(StrEnum):
    """The operand is not one exact extent; its values name no program; the
    transaction ids it holds are not in the CSD; or no CSD was given, so a
    transaction id names no program this run can know."""

    OPERAND_NOT_ONE_EXTENT = "operand-not-one-exact-extent"
    NO_PROGRAM_NAME = "no-program-name"
    TRANSACTION_NOT_IN_CSD = "transaction-not-in-csd"
    NO_CSD = "no-csd"
