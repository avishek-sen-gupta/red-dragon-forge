"""Re-export the ANTLR-based CICS text parser for injection into CobolFrontend."""

from cobble.cics.cics_visitor import CicsOperand, parse_exec_cics_text

__all__ = ["CicsOperand", "parse_exec_cics_text"]
