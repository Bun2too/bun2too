#!/usr/bin/env python3
"""Merge Cobertura reports into one whose file paths are relative to the repository root.

Coverage tools write paths relative to the folder they ran in (a product, a package),
but GitHub matches coverage to files by their path in the repository. Each class
filename becomes <source>/<filename> relative to --root, the merged report has one
<source> of ".", and its line totals are recomputed from the merged classes.

Usage: coverage-paths.py --out OUT.xml [--root DIR] REPORT.xml [REPORT.xml ...]
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET


def classes(report: str, root: str):
    coverage = ET.parse(report).getroot()
    base = coverage.findtext("sources/source")
    base = os.path.realpath(base or os.path.dirname(os.path.abspath(report)))
    for package in coverage.iter("package"):
        for cls in package.iter("class"):
            path = os.path.realpath(os.path.join(base, cls.get("filename", "")))
            rel = os.path.relpath(path, root)
            if rel.startswith(".."):
                raise SystemExit(f"::error::{path} in {report} is outside the repository ({root})")
            cls.set("filename", rel.replace(os.sep, "/"))
            yield cls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE", "."))
    args = parser.parse_args()
    root = os.path.realpath(args.root)

    merged = {}
    for report in args.reports:
        for cls in classes(report, root):
            merged[cls.get("filename")] = cls  # a file reported twice keeps the last report
    if not merged:
        print(f"::error::{', '.join(args.reports)} list no files", file=sys.stderr)
        return 1

    valid = covered = 0
    package = ET.Element("package", name="repository")
    group = ET.SubElement(package, "classes")
    for name in sorted(merged):
        cls = merged[name]
        lines = cls.findall("lines/line")
        hit = sum(1 for line in lines if int(line.get("hits", "0")) > 0)
        valid += len(lines)
        covered += hit
        cls.set("line-rate", f"{hit / len(lines):.4f}" if lines else "1")
        group.append(cls)
    rate = covered / valid if valid else 1.0
    package.set("line-rate", f"{rate:.4f}")
    package.set("branch-rate", "0")

    coverage = ET.Element(
        "coverage",
        {
            "lines-valid": str(valid),
            "lines-covered": str(covered),
            "line-rate": f"{rate:.4f}",
            "branches-valid": "0",
            "branches-covered": "0",
            "branch-rate": "0",
            "complexity": "0",
            "version": "1",
            "timestamp": "0",
        },
    )
    ET.SubElement(ET.SubElement(coverage, "sources"), "source").text = "."
    ET.SubElement(coverage, "packages").append(package)
    ET.ElementTree(coverage).write(args.out, encoding="utf-8", xml_declaration=True)
    print(f"{args.out}: {len(merged)} files, {covered}/{valid} lines, {rate * 100:.1f}% covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
