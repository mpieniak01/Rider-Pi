"""Reproducible Sonar reports from measured Python and Node coverage only."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

import coverage

ROOT = Path(__file__).resolve().parents[1]


def python_report(data_file, output):
    measured = coverage.Coverage(data_file=str(data_file), config_file=False, source=[str(ROOT)])
    measured.load()
    measured.xml_report(
        outfile=str(output),
        include=[str(ROOT / name / "*") for name in ("apps", "services", "common", "drivers", "scripts")],
    )

    tree = ET.parse(output)
    for source in tree.findall(".//sources/source"):
        source.text = "."
    for item in tree.findall(".//class"):
        if not (ROOT / item.attrib["filename"]).is_file():
            raise ValueError("unresolved_python_coverage_source")
    tree.write(output, encoding="utf-8", xml_declaration=True)


def javascript_report(source, output):
    records = []
    for block in source.read_text().split("end_of_record"):
        lines = block.strip().splitlines()
        name = next((line[3:].replace("\\", "/") for line in lines if line.startswith("SF:")), None)
        if name is None:
            continue
        path = Path(name)
        if path.is_absolute():
            path = path.relative_to(ROOT)
        if ".." in path.parts or not (ROOT / path).is_file():
            raise ValueError("coverage_source_outside_repository: " + str(path))
        if path.parts[0] != "web":
            continue  # Test fixtures are Sonar tests, never production coverage.
        limit = len((ROOT / path).read_text().splitlines())
        kept = ["SF:" + path.as_posix()]
        for line in lines:
            if line.startswith(("DA:", "BRDA:")):
                number = int(line.split(":", 1)[1].split(",", 1)[0])
                if number > limit:
                    if number > limit + 1:
                        raise ValueError("coverage_line_outside_source: " + str(path))
                    continue  # The fixture appends one sourceURL/export line to a measured copy.
            if line.startswith(("DA:", "BRDA:")):
                kept.append(line)
        records.append("\n".join([*kept, "end_of_record"]))
    if not records:
        raise ValueError("no_production_javascript_coverage")
    output.write_text("\n".join(records) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-data", type=Path)
    parser.add_argument("--javascript", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.python_data:
        python_report(args.python_data, args.output / "coverage.xml")
    if args.javascript:
        javascript_report(args.javascript, args.output / "lcov.info")


if __name__ == "__main__":
    main()
