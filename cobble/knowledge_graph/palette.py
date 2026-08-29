"""Node and edge colours, shared by every renderer.

One source of colour truth so the vis-network page (render.py) and the WebGL
page (render_webgl.py) show the same corpus in the same colours -- a
stakeholder looking at both should not have to re-learn the legend.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

# Grey, for a kind added to graph_types without a colour here. Visible and
# obviously unstyled, rather than invisible.
DEFAULT_COLOR = "#999999"

NODE_COLORS: Mapping[str, str] = MappingProxyType(
    {
        "PROGRAM": "#4C72B0",
        "COPYBOOK": "#55A868",
        "TRANSACTION": "#C44E52",
        "JOB": "#8172B2",
        "STEP": "#CCB974",
        "DATASET": "#64B5CD",
        "BMS_MAP": "#DD8452",
    }
)

EDGE_COLORS: Mapping[str, str] = MappingProxyType(
    {
        "CALL": "#4C72B0",
        "COPY": "#55A868",
        "XCTL": "#C44E52",
        "LINK": "#C44E52",
        "RETURN_TRANSID": "#C44E52",
        "START_TRANSID": "#C44E52",
        "STARTS": "#8172B2",
        "SENDS_MAP": "#DD8452",
        "RECEIVES_MAP": "#DD8452",
        "JCL_STEP_RUNS": "#8172B2",
        "READS": "#64B5CD",
        "WRITES": "#64B5CD",
        "UPDATES": "#64B5CD",
    }
)
