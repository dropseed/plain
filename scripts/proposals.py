"""Lightweight proposal tracker for the proposals/ directory."""

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

PROPOSALS_DIR = Path(__file__).resolve().parent.parent / "proposals"
SKIP_FILES = {"README.md", "CLAUDE.md"}
NUMBER_RE = re.compile(r"^(\d+)-(.+)")


def parse_frontmatter(path):
    """Parse optional YAML frontmatter from a proposal file."""
    text = path.read_text()
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            try:
                return yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError:
                return {}
    return {}


def get_title(path):
    """Extract the first H1 heading as the title."""
    for line in path.read_text().splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def file_dates(path):
    """Get created and updated dates from filesystem."""
    stat = os.stat(path)
    updated = datetime.fromtimestamp(stat.st_mtime).date()
    created = datetime.fromtimestamp(
        getattr(stat, "st_birthtime", stat.st_mtime)
    ).date()
    return created, updated


def as_list(val):
    if not val:
        return []
    if isinstance(val, str):
        return [val]
    return list(val)


def parse_number(stem):
    """Extract the number prefix from a proposal stem, or None."""
    m = NUMBER_RE.match(stem)
    return int(m.group(1)) if m else None


def load_proposals():
    """Load all proposals with metadata."""
    proposals = []
    for path in sorted(PROPOSALS_DIR.glob("*.md")):
        if path.name in SKIP_FILES:
            continue
        fm = parse_frontmatter(path)
        created, updated = file_dates(path)
        number = parse_number(path.stem)
        proposals.append(
            {
                "path": path,
                "stem": path.stem,
                "title": get_title(path),
                "packages": as_list(fm.get("packages")),
                "after": fm.get("after"),
                "related": as_list(fm.get("related")),
                "created": created,
                "updated": updated,
                "number": number,
            }
        )
    return proposals


def build_graph(proposals):
    """Build relationship graph."""
    neighbors = {p["stem"]: set() for p in proposals}
    for p in proposals:
        for rel in p["related"]:
            if rel in neighbors:
                neighbors[p["stem"]].add(rel)
                neighbors[rel].add(p["stem"])
    for p in proposals:
        p["all_related"] = sorted(neighbors[p["stem"]])


def serializable(p):
    """Convert a proposal dict to JSON-serializable form."""
    d = {
        "stem": p["stem"],
        "title": p["title"],
        "packages": p["packages"],
        "created": str(p["created"]),
        "updated": str(p["updated"]),
    }
    if p["number"] is not None:
        d["number"] = p["number"]
    if p.get("after"):
        d["after"] = p["after"]
    if p.get("all_related"):
        d["related"] = p["all_related"]
    return d


def cmd_list(args, proposals):
    if args.search:
        term = args.search.lower()
        proposals = [
            p
            for p in proposals
            if term in p["title"].lower() or term in p["stem"].lower()
        ]

    sort_key = args.sort or "updated"
    reverse = sort_key in ("updated", "created")
    proposals.sort(key=lambda p: p.get(sort_key, ""), reverse=reverse)

    if args.json:
        print(json.dumps([serializable(p) for p in proposals], indent=2))
        return

    console = Console()
    table = Table(show_lines=False, pad_edge=False, box=None)
    table.add_column("#", style="bold yellow", justify="right")
    table.add_column("Proposal", style="bold", no_wrap=True)
    table.add_column("Packages", style="cyan")
    table.add_column("Updated", style="green")

    for p in proposals:
        table.add_row(
            str(p["number"]) if p["number"] is not None else "",
            p["stem"],
            ", ".join(p["packages"]) or "-",
            str(p["updated"]),
        )

    console.print(table)
    console.print(f"\n[dim]{len(proposals)} proposals[/dim]")


def cmd_show(args, proposals):
    by_stem = {p["stem"]: p for p in proposals}

    name = args.name.replace(".md", "")
    if name not in by_stem:
        matches = [s for s in by_stem if name in s]
        if len(matches) == 1:
            name = matches[0]
        elif matches:
            if args.json:
                print(json.dumps({"error": "ambiguous", "matches": matches}))
            else:
                Console().print(
                    f"Ambiguous name '{name}', matches: {', '.join(matches)}"
                )
            return
        else:
            if args.json:
                print(json.dumps({"error": "not found"}))
            else:
                Console().print(f"No proposal matching '{name}'")
            return

    p = by_stem[name]

    if args.json:
        print(json.dumps(serializable(p), indent=2))
        return

    console = Console()
    if p["number"] is not None:
        console.print(
            f"[bold yellow]#{p['number']}[/bold yellow]  [bold]{p['title']}[/bold]"
        )
    else:
        console.print(f"[bold]{p['title']}[/bold]")
    console.print(f"[dim]File:[/dim] proposals/{p['stem']}.md")
    if p["packages"]:
        console.print(f"[dim]Packages:[/dim] {', '.join(p['packages'])}")
    console.print(f"[dim]Created:[/dim] {p['created']}")
    console.print(f"[dim]Updated:[/dim] {p['updated']}")

    if p.get("all_related"):
        console.print("\n[bold]Related:[/bold]")
        for rel in p["all_related"]:
            if rel in by_stem:
                console.print(f"  [dim]{rel}[/dim]  {by_stem[rel]['title']}")
            else:
                console.print(f"  [red]{rel}[/red]  (not found)")


def cmd_default(args, proposals):
    """Default view: numbered roadmap first, then backlog by package."""
    numbered = sorted(
        [p for p in proposals if p["number"] is not None],
        key=lambda p: p["number"],
    )
    backlog = [p for p in proposals if p["number"] is None]

    if args.json:
        result = {
            "roadmap": [serializable(p) for p in numbered],
            "backlog": {},
        }
        for p in backlog:
            pkg = p["packages"][0] if p["packages"] else "(other)"
            result["backlog"].setdefault(pkg, []).append(serializable(p))
        print(json.dumps(result, indent=2))
        return

    console = Console()

    if numbered:
        tree = Tree("[bold yellow]Roadmap[/bold yellow]")
        for p in numbered:
            label = f"[bold yellow]{p['number']:03d}[/bold yellow]  {p['stem']}"
            if p.get("all_related"):
                label += f"  [dim]see {', '.join(p['all_related'])}[/dim]"
            tree.add(label)
        console.print(tree)
        console.print()

    # Backlog grouped by package
    pkg_groups = {}
    for p in backlog:
        pkg = p["packages"][0] if p["packages"] else "(other)"
        pkg_groups.setdefault(pkg, []).append(p)

    for pkg in sorted(pkg_groups):
        items = sorted(pkg_groups[pkg], key=lambda p: p["stem"])
        tree = Tree(f"[bold]{pkg}[/bold]")
        for p in items:
            label = p["stem"]
            annotations = []
            if p.get("after"):
                annotations.append(f"[yellow]after {p['after']}[/yellow]")
            if p.get("all_related"):
                annotations.append(f"[dim]see {', '.join(p['all_related'])}[/dim]")
            if annotations:
                label += "  " + "  ".join(annotations)
            tree.add(label)
        console.print(tree)
        console.print()


def main():
    parser = argparse.ArgumentParser(description="Proposal tracker")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command")

    ls = sub.add_parser("list", aliases=["ls"], help="List proposals")
    ls.add_argument("--search", "-s", help="Search titles and names")
    ls.add_argument("--sort", choices=["updated", "created", "stem"], default="updated")

    show = sub.add_parser("show", help="Show proposal details")
    show.add_argument("name", help="Proposal name (partial match ok)")

    args = parser.parse_args()

    if not args.command:
        args.command = "default"

    proposals = load_proposals()
    build_graph(proposals)

    if args.command in ("list", "ls"):
        cmd_list(args, proposals)
    elif args.command == "show":
        cmd_show(args, proposals)
    elif args.command == "default":
        cmd_default(args, proposals)


if __name__ == "__main__":
    main()
