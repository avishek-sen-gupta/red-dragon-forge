"""The page's colours: the source CFG page's for the graph, and one each for files, the log and the two queries' paths."""

from collections.abc import Mapping
from types import MappingProxyType

from cobble.dataflow.srccfg.webgl import EDGE_PALETTE as CFG_EDGE_PALETTE
from cobble.dataflow.srccfg.webgl import NODE_PALETTE as CFG_NODE_PALETTE
from cobble.experimental.codeql.demo.drawn_edge import DrawnEdge
from cobble.experimental.codeql.demo.drawn_kind import DrawnKind

NODE_PALETTE: Mapping[str, str] = MappingProxyType(
    {
        **CFG_NODE_PALETTE,
        DrawnKind.READ.value: "#0F7C86",
        DrawnKind.WRITE.value: "#C2410C",
        DrawnKind.REWRITE.value: "#C2410C",
        DrawnKind.DISPLAY.value: "#7C3AED",
    }
)

EDGE_PALETTE: Mapping[str, str] = MappingProxyType(
    {
        **CFG_EDGE_PALETTE,
        DrawnEdge.READ_TO_WRITE.value: "#F59E0B",
        DrawnEdge.READ_TO_DISPLAY.value: "#DB2777",
    }
)
