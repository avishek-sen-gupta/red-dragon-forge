import json
import sys

from .generator import generate_copybook
from .parser import parse_mapsets


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate COBOL symbolic copybooks from hlasm_export JSON"
    )
    parser.add_argument("--input", "-i", default="-", help="JSON file produced by hlasm_export (default: stdin)")
    parser.add_argument("--output", "-o", default="-", help="Output copybook file (default: stdout)")
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        with open(args.input) as f:
            data = json.load(f)

    invocations = data.get("macro_invocations", [])
    mapsets = parse_mapsets(invocations)

    lines: list[str] = []
    for mapset in mapsets:
        lines.extend(generate_copybook(mapset))

    text = "\n".join(lines) + "\n"

    if args.output == "-":
        sys.stdout.write(text)
    else:
        with open(args.output, "w") as f:
            f.write(text)
