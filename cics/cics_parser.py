"""Re-export the ANTLR-based CICS text parser for injection into CobolFrontend."""

from cics.cics_visitor import parse_exec_cics_text
from interpreter.cobol.cobol_statements import CicsOperand

__all__ = ["CicsOperand", "parse_exec_cics_text"]
