from __future__ import annotations

from plain.postgres import get_connection
from plain.postgres.introspection import (
    ColumnState,
    ConstraintState,
    ConType,
    IndexState,
    introspect_table,
    normalize_check_definition,
    normalize_default_sql,
    normalize_expression,
    normalize_index_definition,
)


def _execute(sql: str) -> None:
    with get_connection().cursor() as cursor:
        cursor.execute(sql)


class TestIntrospectTable:
    """Boundary tests: introspect_table() against a real Postgres database."""

    def test_existing_table(self, db):
        """Widget table returns a populated TableState with columns and constraints."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert state.exists

        # Columns include id, name, size
        assert "id" in state.columns
        assert "name" in state.columns
        assert "size" in state.columns
        assert isinstance(state.columns["id"], ColumnState)
        assert state.columns["id"].not_null is True
        assert state.columns["name"].not_null is True

        # Has the unique constraint from the model
        assert "unique_widget_name_size" in state.constraints
        uc = state.constraints["unique_widget_name_size"]
        assert isinstance(uc, ConstraintState)
        assert uc.constraint_type == ConType.UNIQUE
        assert uc.validated is True

    def test_nonexistent_table(self, db):
        """A table that doesn't exist returns TableState(exists=False)."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "this_table_does_not_exist")

        assert state.exists is False
        assert state.columns == {}
        assert state.indexes == {}

    def test_indexes_separated_from_constraints(self, db):
        """Indexes go to state.indexes, constraints go to state.constraints."""
        _execute(
            'CREATE INDEX "examples_widget_name_idx" ON "examples_widget" ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "examples_widget_name_idx" in state.indexes
        idx = state.indexes["examples_widget_name_idx"]
        assert isinstance(idx, IndexState)
        assert idx.columns == ["name"]
        assert idx.is_valid is True

        # The unique constraint should be in constraints, not indexes
        assert "unique_widget_name_size" not in state.indexes
        assert "unique_widget_name_size" in state.constraints

    def test_invalid_index(self, db):
        """An index marked INVALID in pg_catalog is reported as is_valid=False."""
        _execute('CREATE INDEX "examples_widget_bad_idx" ON "examples_widget" ("name")')
        _execute(
            """
            UPDATE pg_index SET indisvalid = false
            WHERE indexrelid = (SELECT oid FROM pg_class WHERE relname = 'examples_widget_bad_idx')
            """
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert state.indexes["examples_widget_bad_idx"].is_valid is False

    def test_check_constraint(self, db):
        """Check constraints land in state.constraints with contype 'c'."""
        _execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "widget_id_positive" CHECK ("id" > 0)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "widget_id_positive" in state.constraints
        cc = state.constraints["widget_id_positive"]
        assert isinstance(cc, ConstraintState)
        assert cc.constraint_type == ConType.CHECK
        assert cc.validated is True
        assert cc.definition is not None
        assert "id" in cc.definition

    def test_not_valid_constraint(self, db):
        """A NOT VALID constraint is reported as validated=False."""
        _execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "widget_id_positive"'
            ' CHECK ("id" > 0) NOT VALID'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert state.constraints["widget_id_positive"].validated is False

    def test_foreign_keys(self, db):
        """Foreign keys are in state.constraints with contype 'f' and target info."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widgettag")

        # WidgetTag has FKs to Widget and Tag
        fk_constraints = {
            k: v
            for k, v in state.constraints.items()
            if v.constraint_type == ConType.FOREIGN_KEY
        }
        fk_targets = {
            (v.target_table, v.target_column) for v in fk_constraints.values()
        }
        assert ("examples_widget", "id") in fk_targets
        assert ("examples_tag", "id") in fk_targets

        # Verify FK structure
        for cs in fk_constraints.values():
            assert isinstance(cs, ConstraintState)
            assert cs.columns  # not empty
            assert cs.target_table is not None
            assert cs.target_column is not None

    def test_primary_key_in_constraints(self, db):
        """Primary key appears in constraints with contype 'p'."""
        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        pk_constraints = {
            k: v
            for k, v in state.constraints.items()
            if v.constraint_type == ConType.PRIMARY
        }
        assert len(pk_constraints) == 1
        pk = next(iter(pk_constraints.values()))
        assert "id" in pk.columns

    def test_exclusion_constraint(self, db):
        """Exclusion constraints land in constraints with contype 'x'."""
        _execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        _execute(
            'ALTER TABLE "examples_widget" ADD CONSTRAINT "widget_name_excl"'
            ' EXCLUDE USING gist ("name" WITH =)'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "widget_name_excl" in state.constraints
        xc = state.constraints["widget_name_excl"]
        assert xc.constraint_type == ConType.EXCLUSION
        assert xc.validated is True
        assert xc.definition is not None

    def test_hash_index(self, db):
        """Non-btree indexes are stored with their access method."""
        _execute(
            'CREATE INDEX "examples_widget_name_hash" ON "examples_widget" USING hash ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "examples_widget_name_hash" in state.indexes
        idx = state.indexes["examples_widget_name_hash"]
        assert idx.access_method == "hash"
        assert idx.is_unique is False
        assert idx.is_valid is True

    def test_unique_index_without_constraint(self, db):
        """A CREATE UNIQUE INDEX (no backing constraint) has is_unique=True."""
        _execute(
            'CREATE UNIQUE INDEX "examples_widget_name_uniq_idx"'
            ' ON "examples_widget" ("name")'
        )

        conn = get_connection()
        with conn.cursor() as cursor:
            state = introspect_table(conn, cursor, "examples_widget")

        assert "examples_widget_name_uniq_idx" in state.indexes
        idx = state.indexes["examples_widget_name_uniq_idx"]
        assert idx.is_unique is True


class TestNormalizeCheckDefinition:
    """Unit tests for the pure normalization function."""

    def test_strips_check_wrapper(self):
        assert normalize_check_definition("CHECK (id > 0)") == "id > 0"

    def test_collapses_whitespace(self):
        assert normalize_check_definition("CHECK (id   >   0)") == "id > 0"

    def test_removes_quotes(self):
        assert normalize_check_definition('CHECK ("id" > 0)') == "id > 0"

    def test_strips_redundant_parens(self):
        assert normalize_check_definition("CHECK ((id > 0))") == "id > 0"

    def test_preserves_balanced_inner_parens(self):
        result = normalize_check_definition("CHECK ((a > 0) AND (b > 0))")
        assert "a > 0" in result
        assert "b > 0" in result

    def test_lowercases(self):
        assert normalize_check_definition("CHECK (ID > 0)") == "id > 0"

    def test_handles_bare_expression(self):
        assert normalize_check_definition("id > 0") == "id > 0"

    def test_strips_type_casts(self):
        """PG adds explicit type casts to stored definitions."""
        assert (
            normalize_check_definition("CHECK (username <> ''::text)")
            == "username <> ''"
        )

    def test_preserves_cast_like_text_inside_string_literal(self):
        """`::` inside a quoted string must not be mistaken for a cast."""
        assert (
            normalize_check_definition("CHECK (note <> 'a::b'::text)")
            == "note <> 'a::b'"
        )

    def test_preserves_escaped_quotes_inside_string_literal(self):
        """SQL escapes single quotes by doubling them; must not terminate the string early."""
        assert (
            normalize_check_definition("CHECK (note <> 'it''s'::text)")
            == "note <> 'it''s'"
        )

    def test_strips_casts_with_multiple_literals(self):
        assert (
            normalize_check_definition(
                "CHECK (status = 'active'::text OR status = 'paused'::text)"
            )
            == "status = 'active' or status = 'paused'"
        )


class TestNormalizeExpression:
    """Unit tests for normalize_expression — used by convergence to compare
    index expressions between pg_get_indexdef output and ORM-compiled SQL."""

    def test_simple_lower(self):
        assert normalize_expression('LOWER("slug")') == "lower(slug)"

    def test_strips_type_cast(self):
        """PG adds explicit casts: lower((slug)::text) for varchar columns."""
        assert normalize_expression("lower((slug)::text)") == "lower(slug)"

    def test_strips_type_cast_in_multi_expression(self):
        assert (
            normalize_expression("lower((slug)::text), team_id")
            == "lower(slug), team_id"
        )

    def test_orm_paren_wrapping_matches_pg(self):
        """ORM wraps each IndexExpression in parens; PG doesn't.
        These must normalize to the same string."""
        pg = "lower((slug)::text), team_id"
        orm = '(LOWER("slug")), "team_id"'
        assert normalize_expression(pg) == normalize_expression(orm)

    def test_single_expression_paren_wrapping(self):
        pg = "lower((slug)::text)"
        orm = '(LOWER("slug"))'
        assert normalize_expression(pg) == normalize_expression(orm)

    def test_plain_columns(self):
        assert normalize_expression("slug, team_id") == "slug, team_id"

    def test_multiple_function_expressions(self):
        pg = "lower((name)::text), upper((email)::text), team_id"
        orm = '(LOWER("name")), (UPPER("email")), "team_id"'
        assert normalize_expression(pg) == normalize_expression(orm)


class TestNormalizeIndexDefinition:
    def test_strips_prefix_with_using(self):
        result = normalize_index_definition(
            "CREATE INDEX foo ON bar USING btree (upper(email))"
        )
        assert result == "upper(email)"

    def test_strips_prefix_without_using(self):
        result = normalize_index_definition(
            'CREATE INDEX CONCURRENTLY "foo" ON "bar" (UPPER("email"))'
        )
        assert result == "upper(email)"

    def test_strips_schema_prefix(self):
        result = normalize_index_definition(
            "CREATE INDEX foo ON public.bar USING btree (upper(email))"
        )
        assert result == "upper(email)"

    def test_multi_expression(self):
        result = normalize_index_definition(
            "CREATE INDEX foo ON bar USING btree (lower(name), upper(email))"
        )
        assert result == "lower(name), upper(email)"

    def test_matching_definitions(self):
        """pg_get_indexdef and model-generated SQL normalize to the same string."""
        db_def = "CREATE INDEX foo ON public.bar USING btree (upper(email))"
        model_def = 'CREATE INDEX CONCURRENTLY "new_foo" ON "bar" (UPPER("email"))'
        assert normalize_index_definition(db_def) == normalize_index_definition(
            model_def
        )

    def test_with_where_clause(self):
        """normalize_index_definition preserves WHERE clause as-is (structured
        comparison handles WHERE separately)."""
        result = normalize_index_definition(
            "CREATE UNIQUE INDEX foo ON public.bar USING btree (lower(username)) WHERE (NOT (username = ''::text))"
        )
        assert "where" in result
        assert "lower(username)" in result


class TestNormalizeDefaultSql:
    """Unit tests for normalize_default_sql — used to compare column DEFAULT
    expressions between pg_get_expr output and ORM-compiled SQL."""

    def test_lowercases_function_call(self):
        assert normalize_default_sql("STATEMENT_TIMESTAMP()") == "statement_timestamp()"

    def test_strips_type_cast_on_string_literal(self):
        assert normalize_default_sql("'pending'::text") == "'pending'"

    def test_strips_type_cast_on_int_literal(self):
        assert normalize_default_sql("0::integer") == "0"

    def test_function_call_parens_preserved(self):
        """Balanced-paren stripping must not eat the argless () from a call."""
        assert normalize_default_sql("gen_random_uuid()") == "gen_random_uuid()"

    def test_matching_defaults(self):
        """pg_get_expr output and ORM-compiled SQL normalize to the same string."""
        pg = "statement_timestamp()"
        orm = "STATEMENT_TIMESTAMP()"
        assert normalize_default_sql(pg) == normalize_default_sql(orm)

    def test_preserves_cast_like_text_inside_string_literal(self):
        """A default like `'a::b'::text` keeps its inner `::b`."""
        assert normalize_default_sql("'a::b'::text") == "'a::b'"

    def test_preserves_escaped_quotes_inside_string_literal(self):
        assert normalize_default_sql("'it''s'::text") == "'it''s'"

    def test_strips_cast_on_function_call_operand(self):
        """PG wraps function-call operands like `(length(col))::text`; the
        bare-cast branch drops `::text` and the balanced-paren step then
        strips the grouping parens."""
        assert normalize_default_sql("(length(col))::text") == "length(col)"

    def test_handles_coalesce_with_literal_cast(self):
        assert (
            normalize_default_sql("coalesce('pending'::text, 'default'::text)")
            == "coalesce('pending', 'default')"
        )

    def test_strips_array_type_suffix(self):
        """`::text[]` — the `[]` suffix is part of the type and must go too."""
        assert normalize_default_sql("'{a,b}'::text[]") == "'{a,b}'"

    def test_strips_parameterized_type_suffix(self):
        """`::varchar(10)` — the `(10)` suffix is part of the type and must go too."""
        assert normalize_default_sql("'abc'::varchar(10)") == "'abc'"

    def test_strips_numeric_with_precision_and_scale(self):
        assert normalize_default_sql("1.5::numeric(10, 2)") == "1.5"

    def test_strips_multiword_time_type(self):
        """PG emits ``time without time zone`` for the ``time`` alias —
        psycopg's model-side cast drops to ``::time``, so both must normalize
        to the same literal or TimeField defaults drift every sync."""
        assert normalize_default_sql(
            "'12:00:00'::time without time zone"
        ) == normalize_default_sql("'12:00:00'::time")

    def test_strips_multiword_timestamp_type(self):
        assert normalize_default_sql(
            "'2020-01-01'::timestamp with time zone"
        ) == normalize_default_sql("'2020-01-01'::timestamptz")

    def test_strips_character_varying(self):
        assert normalize_default_sql("'x'::character varying") == normalize_default_sql(
            "'x'::varchar"
        )

    def test_strips_double_precision(self):
        assert normalize_default_sql("1.5::double precision") == "1.5"

    def test_strips_redundant_wrap_around_function_call(self):
        """pg_get_expr wraps trivial expressions in grouping parens; the
        compiler doesn't — they must not drive spurious drift."""
        assert normalize_default_sql("(gen_random_uuid())") == "gen_random_uuid()"

    def test_strips_nested_redundant_wraps(self):
        assert normalize_default_sql("((gen_random_uuid()))") == "gen_random_uuid()"

    def test_strips_redundant_wrap_around_arithmetic(self):
        """Grouping parens around arithmetic are redundant for comparison."""
        assert (
            normalize_default_sql("(1 + mod(get_byte(x, 0), 36))")
            == "1 + mod(get_byte(x, 0), 36)"
        )

    def test_preserves_function_call_argument_parens(self):
        """`coalesce(a, b)` parens are call syntax — must stay."""
        assert normalize_default_sql("coalesce(a, b)") == "coalesce(a, b)"

    def test_preserves_row_constructor_parens(self):
        """Top-level comma inside parens means it's a row/tuple, not grouping."""
        assert normalize_default_sql("(1, 2)") == "(1, 2)"

    def test_leaves_parens_inside_string_literal(self):
        """`(` and `)` inside a quoted literal are content, not syntax."""
        assert normalize_default_sql("'a(b)c'") == "'a(b)c'"

    def test_leaves_parens_inside_literal_with_escaped_quote(self):
        """SQL doubles `'` to escape it inside string literals — the tokenizer
        must not mistake the doubled quote for a literal boundary."""
        assert normalize_default_sql("'it''s (ok)'") == "'it''s (ok)'"
