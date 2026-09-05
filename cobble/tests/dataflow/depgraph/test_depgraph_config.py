import pytest

from cobble.dataflow.depgraph.config import (
    DEFAULT_COLLAPSE_WINDOW,
    depgraph_config_from_dict,
)

_MINIMAL = {"output": {"asg_dir": "out-parsed", "graph_dir": "out-depgraph"}}


def test_a_depgraph_config_needs_no_source_section() -> None:
    """The depgraph reads the cache, it does not build it. Naming the corpus and
    the bridge JAR here would let this config disagree with the parse config that
    actually produced the ASGs -- and the graph would then be a graph of members
    nobody parsed."""
    config = depgraph_config_from_dict(_MINIMAL)

    assert str(config.asg_dir) == "out-parsed"
    assert str(config.graph_dir) == "out-depgraph"


def test_a_depgraph_config_with_no_collapse_section_is_round_one() -> None:
    """Literal connectivity, nothing collapsed, is a legitimate way to run this."""
    config = depgraph_config_from_dict(_MINIMAL)

    assert config.passthrough_names == ()
    assert config.passthrough_patterns == ()
    assert config.collapse_window == DEFAULT_COLLAPSE_WINDOW


def test_a_depgraph_config_reads_the_pass_through_judgment() -> None:
    config = depgraph_config_from_dict(
        {
            **_MINIMAL,
            "collapse": {
                "window": 2,
                "passthrough_names": ["WS-EDIT"],
                "passthrough_patterns": ["^WS-TMP"],
            },
        }
    )

    assert config.collapse_window == 2
    assert config.passthrough_names == ("WS-EDIT",)
    assert config.passthrough_patterns == ("^WS-TMP",)


def test_a_depgraph_config_missing_its_asg_dir_raises() -> None:
    with pytest.raises(KeyError, match="asg_dir"):
        depgraph_config_from_dict({"output": {"graph_dir": "out-depgraph"}})
