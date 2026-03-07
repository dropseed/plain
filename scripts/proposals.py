"""Lightweight proposal tracker for the proposals/ directory."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

PROPOSALS_DIR = Path(__file__).resolve().parent.parent / "proposals"
SKIP_FILES = {"README.md", "CLAUDE.md"}


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


def load_proposals():
    """Load all proposals with metadata."""
    proposals = []
    for path in sorted(PROPOSALS_DIR.glob("*.md")):
        if path.name in SKIP_FILES:
            continue
        fm = parse_frontmatter(path)
        created, updated = file_dates(path)
        proposals.append(
            {
                "path": path,
                "stem": path.stem,
                "title": get_title(path),
                "packages": as_list(fm.get("packages")),
                "depends_on": as_list(fm.get("depends_on")),
                "related": as_list(fm.get("related")),
                "created": created,
                "updated": updated,
            }
        )
    return proposals


def build_graph(proposals):
    """Build dependency and relationship graphs."""
    by_stem = {p["stem"]: p for p in proposals}

    for p in proposals:
        p["blocks"] = []

    for p in proposals:
        for dep in p["depends_on"]:
            if dep in by_stem:
                by_stem[dep]["blocks"].append(p["stem"])

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
    if p["depends_on"]:
        d["depends_on"] = p["depends_on"]
    if p.get("blocks"):
        d["blocks"] = p["blocks"]
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
    table.add_column("Proposal", style="bold", no_wrap=True)
    table.add_column("Packages", style="cyan")
    table.add_column("Updated", style="green")
    table.add_column("Deps", style="yellow", justify="right")
    table.add_column("Blocks", style="red", justify="right")

    for p in proposals:
        deps = len(p["depends_on"])
        blocks = len(p.get("blocks", []))
        table.add_row(
            p["stem"],
            ", ".join(p["packages"]) or "-",
            str(p["updated"]),
            str(deps) if deps else "",
            str(blocks) if blocks else "",
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
    console.print(f"[bold]{p['title']}[/bold]")
    console.print(f"[dim]File:[/dim] proposals/{p['stem']}.md")
    if p["packages"]:
        console.print(f"[dim]Packages:[/dim] {', '.join(p['packages'])}")
    console.print(f"[dim]Created:[/dim] {p['created']}")
    console.print(f"[dim]Updated:[/dim] {p['updated']}")

    if p["depends_on"]:
        console.print("\n[bold yellow]Depends on:[/bold yellow]")
        for dep in p["depends_on"]:
            if dep in by_stem:
                console.print(f"  [yellow]{dep}[/yellow]  {by_stem[dep]['title']}")
            else:
                console.print(f"  [red]{dep}[/red]  (not found)")

    if p.get("blocks"):
        console.print("\n[bold red]Blocks:[/bold red]")
        for b in sorted(p["blocks"]):
            if b in by_stem:
                console.print(f"  [red]{b}[/red]  {by_stem[b]['title']}")

    if p.get("all_related"):
        console.print("\n[bold]Related:[/bold]")
        for rel in p["all_related"]:
            if rel in by_stem:
                console.print(f"  [dim]{rel}[/dim]  {by_stem[rel]['title']}")
            else:
                console.print(f"  [red]{rel}[/red]  (not found)")


def cmd_default(args, proposals):
    """Default view: dependency trees by package."""
    by_stem = {p["stem"]: p for p in proposals}

    if args.json:
        pkg_groups = {}
        for p in proposals:
            pkg = p["packages"][0] if p["packages"] else "(other)"
            pkg_groups.setdefault(pkg, []).append(serializable(p))
        print(json.dumps(pkg_groups, indent=2))
        return

    console = Console()

    # Group by primary package
    pkg_groups = {}
    for p in proposals:
        pkg = p["packages"][0] if p["packages"] else "(other)"
        pkg_groups.setdefault(pkg, []).append(p)

    for pkg in sorted(pkg_groups):
        items = pkg_groups[pkg]
        stems_in_pkg = {p["stem"] for p in items}

        # Roots: proposals that have no depends_on within this package
        roots = []
        has_parent = set()
        for p in items:
            for dep in p["depends_on"]:
                if dep in stems_in_pkg:
                    has_parent.add(p["stem"])

        roots = [p for p in items if p["stem"] not in has_parent]
        roots.sort(key=lambda p: p["stem"])

        tree = Tree(f"[bold]{pkg}[/bold]")

        rendered = set()

        def add_node(parent, p):
            if p["stem"] in rendered:
                parent.add(f"[dim]{p['stem']}  (see above)[/dim]")
                return
            rendered.add(p["stem"])

            label = p["stem"]
            annotations = []
            # Show cross-package deps
            cross_deps = [d for d in p["depends_on"] if d not in stems_in_pkg]
            if cross_deps:
                annotations.append(f"[yellow]after {', '.join(cross_deps)}[/yellow]")
            # Show related by name
            if p.get("all_related"):
                annotations.append(f"[dim]see {', '.join(p['all_related'])}[/dim]")

            if annotations:
                label += "  " + "  ".join(annotations)

            # Children: things this blocks within the package
            children = sorted(
                [by_stem[b] for b in p.get("blocks", []) if b in stems_in_pkg],
                key=lambda x: x["stem"],
            )

            if children:
                node = parent.add(label)
                for child in children:
                    add_node(node, child)
            else:
                parent.add(label)

        for p in roots:
            add_node(tree, p)

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
