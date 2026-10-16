"""Serve a CICS region to 3270 emulators.

. ./bridge-env.sh
uv run catnip install config/carddemo/data.toml --system /tmp/carddemo-system
uv run cicada-tn3270 --config cicada/config/carddemo-tn3270.toml --port 3270
c3270 -model 3279-2-E localhost:3270   # 3279 + -E, or you get monochrome
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from collections.abc import Sequence
from functools import partial
from pathlib import Path

from catnip.system_catalog import SystemCatalog
from cics.tn3270.config import RegionConfig, load_config
from cics.tn3270.region import ServedRegion, assemble_region, compile_region_package
from cics.tn3270.session import run_session
from cics.tn3270.wire import bind, serve_forever
from litter.open import open_package

logger = logging.getLogger(__name__)


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3270)
    return parser.parse_args(argv)


def _served(config: RegionConfig, bridge_jar: str, work_dir: Path) -> ServedRegion:
    package = compile_region_package(config, bridge_jar, work_dir, work_dir / "out")
    return assemble_region(open_package(package), SystemCatalog(config.system))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = _arguments(sys.argv[1:])
    config = load_config(args.config)
    with tempfile.TemporaryDirectory(prefix="cicada-tn3270-") as work_dir:
        served = _served(config, os.environ["PROLEAP_BRIDGE_JAR"], Path(work_dir))
        server = bind(args.host, args.port)
        logger.info("serving %s on %s:%d", args.config, args.host, args.port)
        session = partial(
            run_session,
            driver=served.driver,
            catalog=served.catalog,
            initial_transid=config.initial_transid,
        )
        serve_forever(server, session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
