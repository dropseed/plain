import json

import click

from ..describe import ModelDescription, describe_models


@click.command()
@click.argument("targets", nargs=-1)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option(
    "--all",
    "include_packages",
    is_flag=True,
    help="Include models from installed packages, not just the app's",
)
def models(
    targets: tuple[str, ...],
    output_json: bool,
    include_packages: bool,
) -> None:
    """Describe the data model: fields, relations, constraints.

    TARGETS narrow the output to models (`Thread`, `changes.Thread`) or whole
    packages (`changes`). Read from the model registry, so no database is needed.
    """
    if include_packages and targets:
        raise click.UsageError(
            "--all widens the default selection; with targets it has nothing to do."
        )

    try:
        descriptions = describe_models(targets, include_packages=include_packages)
    except LookupError as e:
        raise click.ClickException(str(e)) from e

    if output_json:
        click.echo(
            json.dumps({"models": [d.to_dict() for d in descriptions]}, indent=2)
        )
    else:
        for i, description in enumerate(descriptions):
            if i > 0:
                click.echo()
            _render_model(description)


def _render_model(description: ModelDescription) -> None:
    click.secho(description.label, bold=True, nl=False)
    click.secho(f"  →  {description.table}", dim=True)

    for model_field in description.fields:
        type_name = model_field.type.removesuffix("Field")
        marks = []
        if model_field.primary_key:
            marks.append(click.style("PK", fg="yellow"))
        if model_field.unique:
            marks.append(click.style("unique", fg="yellow"))
        if model_field.null:
            marks.append(click.style("null", dim=True))
        click.echo(
            f"  {model_field.name:24s}  {_pad(styled=click.style(type_name, fg='cyan'), visible_length=len(type_name))}  {' '.join(marks)}".rstrip()
        )

    for relation in description.relations:
        if relation.type == "ManyToManyField":
            target = f"⇆ {relation.to}"
            marks = [click.style(f"through {relation.through}", dim=True)]
        else:
            target = f"→ {relation.to}"
            marks = [_style_on_delete(relation.on_delete)]
            if relation.unique:
                marks.append(click.style("1:1", fg="yellow"))
            if relation.null:
                marks.append(click.style("null", dim=True))
        click.echo(
            f"  {relation.name:24s}  {_pad(styled=click.style(target, fg='cyan'), visible_length=len(target))}  {' '.join(marks)}"
        )

    for reverse in description.reverse:
        source = f"{reverse.from_model}.{reverse.field}"
        marks = []
        if reverse.accessor:
            marks.append(click.style(f".{reverse.accessor}", fg="cyan"))
        if reverse.one_to_one:
            marks.append(click.style("1:1", fg="yellow"))
        if reverse.type == "ManyToManyField":
            marks.append(click.style("many-to-many", dim=True))
        marks.append(click.style(f"filter: {reverse.query_name}", dim=True))
        click.echo(f"  {click.style('←', dim=True)} {source:48s}  {' '.join(marks)}")

    for constraint in description.constraints:
        if constraint.kind == "unique":
            detail = _columns_detail(
                columns=constraint.fields or constraint.expressions,
                condition=constraint.condition,
            )
        else:
            detail = constraint.check or ""
        _echo_schema_line(kind=constraint.kind, name=constraint.name, detail=detail)

    for index in description.indexes:
        detail = _columns_detail(
            columns=index.fields or index.expressions, condition=index.condition
        )
        _echo_schema_line(kind="index", name=index.name, detail=detail)


def _columns_detail(*, columns: list[str], condition: str | None) -> str:
    """`(a, b)`, plus ` WHERE ...` for a partial constraint or index.

    Expressions arrive parenthesized the way their DDL writes them, so an
    expression index reads `((LOWER("name")))`, as in `CREATE INDEX`."""
    detail = f"({', '.join(columns)})"
    if condition:
        detail += f" WHERE {condition}"
    return detail


def _pad(*, styled: str, visible_length: int, width: int = 22) -> str:
    """Pad after the styled text, so the ANSI codes don't count toward the width."""
    return styled + " " * max(width - visible_length, 0)


def _echo_schema_line(*, kind: str, name: str, detail: str) -> None:
    click.echo(
        f"  {click.style(f'{kind:8s}', dim=True)} {name}  {click.style(detail, dim=True)}"
    )


def _style_on_delete(on_delete: str | None) -> str:
    if on_delete == "CASCADE":
        return click.style(on_delete, fg="red")
    if on_delete == "SET_NULL":
        return click.style(on_delete, fg="yellow")
    return click.style(on_delete or "", fg="blue")
