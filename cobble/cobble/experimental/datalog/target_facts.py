"""Every dynamic site the combine answered, with its candidates and reasons, as facts."""

from pathlib import Path

from cobble.dataflow.fixpoint.target_site import TargetSite
from cobble.experimental.datalog.column import symbol
from cobble.experimental.datalog.facts import Facts, Row
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines

_SITE = (
    symbol("caller"),
    symbol("n"),
    symbol("kind"),
    symbol("transfer"),
    symbol("expr"),
)
TARGET_SITE = Relation("target_site", _SITE)
TARGET = Relation("target", (*_SITE, symbol("cand")))
TARGET_REASON = Relation(
    "target_reason", (symbol("caller"), symbol("n"), symbol("why"))
)


def _site(site: TargetSite) -> Row:
    return (site.caller, site.node, site.kind.value, site.transfer, site.expression)


def target_facts(run: Path) -> tuple[Facts, ...]:
    sites = tuple(
        TargetSite.model_validate_json(line)
        for line in lines(run / "combine" / "targets.jsonl")
    )
    return (
        Facts(TARGET_SITE, tuple(map(_site, sites))),
        Facts(
            TARGET,
            tuple((*_site(site), name) for site in sites for name in site.candidates),
        ),
        Facts(
            TARGET_REASON,
            tuple(
                (site.caller, site.node, why) for site in sites for why in site.reasons
            ),
        ),
    )
