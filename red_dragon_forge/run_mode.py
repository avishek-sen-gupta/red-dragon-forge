"""The env.toml sections that each name a forge-run mode; exactly one is present."""

from enum import StrEnum


class RunMode(StrEnum):
    PLAIN = "plain"
    JCL = "jcl"
    CICS = "cics"
