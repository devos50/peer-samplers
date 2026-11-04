#!/usr/bin/env python3
"""Stage the saved interactive reports and their downloads for GitHub Pages."""
import argparse
import json
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.in_data = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.urls.extend(attrs[key] for key in ("href", "src") if attrs.get(key))
        if tag == "script" and attrs.get("id") == "data":
            self.in_data = True

    def handle_data(self, data):
        if self.in_data:
            self.urls.extend(link["href"] for link in json.loads(data).get("links", []))

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_data = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("_site"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "site/index.html", output / "index.html")
    (output / ".nojekyll").touch()

    files = {Path("results/scale-study.html")}
    for folder in [root / "results/comparison", *(root / "results/scaled").glob("*-peers-400-rounds*")]:
        for name in ("report.html", "results.json", "summary.csv", "timeseries.csv"):
            files.add((folder / name).relative_to(root))
    for name in ("summary.csv", "paired_comparisons.csv", "run_metrics.csv", "analysis.json"):
        files.add(Path("results/scaled") / name)
    budget = root / "results/peerswap-budget"
    if (budget / "report.html").exists():
        for name in ("report.html", "summary.csv", "paired-comparisons.csv", "run-metrics.csv",
                     "tuning-scores.csv", "selected-configurations.csv", "selection.json",
                     "plan.json", "analysis.json"):
            files.add(Path("results/peerswap-budget") / name)
    for relative in sorted(files):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, destination)

    count = 0
    for page in output.rglob("*.html"):
        links = Links()
        links.feed(page.read_text())
        for url in links.urls:
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (page.parent / unquote(parsed.path)).resolve()
            if not target.is_relative_to(output) or not target.is_file():
                raise ValueError(f"Broken or non-relative site link in {page}: {url}")
            count += 1
    total = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    print(f"Staged {len(files) + 2} files ({total:,} bytes); validated {count} local links in {output}")


if __name__ == "__main__":
    main()
