"""The SQL desk's questions can be graded: every reference query runs read-only and fixes
one answer, and the three splits have the same shape. No model is called."""

import re
import sqlite3
from collections import Counter

import pytest

from examples.sql_desk import target
from examples.sql_desk.shop import build
from examples.sql_desk.tasks import QUESTIONS

SPLITS = {"dev": 24, "val": 36, "test": 36}
LEVELS = {"easy", "medium", "hard"}
# The "best of each group" questions and their number of groups. Their reference queries
# keep every row that ties for a group's best, so one row per group means no group ties.
BEST_PER_GROUP = {
    "dev-top-product-per-category": 6,
    "val-top-customer-per-country": 7,
    "test-top-category-per-month": 6,
}


def each(keep=lambda q: True):
    return pytest.mark.parametrize("q", [q for q in QUESTIONS if keep(q)], ids=lambda q: q.id)


def test_splits_ids_and_levels():
    assert Counter(q.split for q in QUESTIONS) == SPLITS
    assert len({q.id for q in QUESTIONS}) == len(QUESTIONS)
    for q in QUESTIONS:
        assert q.id.startswith(q.split + "-") and q.level in LEVELS, q.id
    for split, n in SPLITS.items():
        levels = Counter(q.level for q in QUESTIONS if q.split == split)
        assert set(levels) == LEVELS, split
        assert all(abs(k - n / 3) <= 3 for k in levels.values()), (split, levels)


def test_no_question_or_query_is_repeated():
    questions = Counter(" ".join(re.findall(r"[a-z0-9]+", q.question.lower())) for q in QUESTIONS)
    queries = Counter(" ".join(q.sql.lower().split()) for q in QUESTIONS)
    assert not [text for text, n in (questions + queries).items() if n > 1]


@each()
def test_reference_query_reads_1_to_50_rows(q):
    rows, error, wrote = target.run_sql(q.sql)
    assert error is None and not wrote, error
    assert 1 <= len(rows) <= 50
    # An amount is whole or given to the cent, never a longer fraction.
    assert all(round(v, 2) == v for row in rows for v in row if isinstance(v, float)), rows


@pytest.fixture(scope="module")
def shop(tmp_path_factory):
    con = sqlite3.connect(build(tmp_path_factory.mktemp("shop") / "shop.sqlite"))
    yield con
    con.close()


def sort_keys(q, shop):
    """What the reference query sorts by, row by row and one row past its LIMIT. Every
    ORDER BY term has to be an output column, or this fails."""
    head, _, tail = q.sql.rpartition(" ORDER BY ")
    terms, _, limit = tail.partition(" LIMIT ")
    cursor = shop.execute(f"{head} ORDER BY {terms}")
    names = [d[0] for d in cursor.description]
    columns = [names.index(term.split()[0]) for term in terms.split(",")]
    rows = cursor.fetchall()[: int(limit) + 1 if limit else None]
    return [tuple(row[i] for i in columns) for row in rows]


@each(lambda q: q.ordered or " LIMIT " in q.sql)
def test_no_tie_decides_the_answer(q, shop):
    keys = sort_keys(q, shop)
    pairs = list(zip(keys, keys[1:], strict=False))
    # In an ordered answer no two neighbours may tie, the row past the LIMIT included. In
    # a top N that is compared as a set, only the cut-off matters.
    assert all(a != b for a, b in (pairs if q.ordered else pairs[-1:])), keys


def test_best_of_each_group_is_unique():
    for task_id, groups in BEST_PER_GROUP.items():
        assert len(target.expected(task_id)) == groups, task_id


def test_every_customer_has_one_latest_order(shop):
    # test-last-order-cancelled asks about a customer's "most recently placed order".
    latest = "SELECT MAX(placed_at) FROM orders x WHERE x.customer_id = o.customer_id"
    counts = f"SELECT COUNT(*) FROM orders o WHERE placed_at = ({latest}) GROUP BY customer_id"
    assert {n for (n,) in shop.execute(counts)} == {1}


def unrounded(sql):
    """The statement with every ROUND(x, 2) replaced by (x)."""
    while (start := sql.find("ROUND(")) >= 0:
        end, depth = start + 6, 1
        while depth:
            depth += {"(": 1, ")": -1}.get(sql[end], 0)
            end += 1
        inner = sql[start + 6 : end - 1]
        assert inner.endswith(", 2"), inner
        sql = f"{sql[:start]}({inner[:-3]}){sql[end:]}"
    return sql


@each(lambda q: "ROUND(" in q.sql)
def test_a_query_that_does_not_round_gets_the_same_rows(q):
    rows, error, _ = target.run_sql(unrounded(q.sql))
    assert error is None, error
    assert target._norm(rows, q.ordered) == target.expected(q.id)
    # No value sits on half a cent, where two ways of computing it could round apart.
    numbers = [v for row in rows for v in row if isinstance(v, float)]
    assert all(abs(abs(v) * 100 % 1 - 0.5) > 1e-6 for v in numbers), numbers


def test_database_build_is_deterministic(tmp_path):
    first, second = build(tmp_path / "a.sqlite"), build(tmp_path / "b.sqlite")
    assert first.read_bytes() == second.read_bytes()


def test_seed_harness_is_valid():
    assert target.validate(target.HERE / "seed") == []


def test_a_column_can_move_only_if_it_moves_in_every_row():
    from harness_evals import Episode

    q = target.BY_ID["test-kitchen-list-vs-lowest-paid"]
    rows, _, _ = target.run_sql(q.sql)
    swapped = [[name, low, price] for name, price, low in rows]

    def passes(answer):
        return target.USECASE.grade([Episode(q.id, extra={"rows": answer})])[0].passed

    assert passes(rows) and passes(swapped)
    swapped[0] = rows[0]
    assert not passes(swapped)


def test_openai_cost_and_reference_without_shop_source(tmp_path, monkeypatch):
    from examples.sql_desk.shop import Db

    monkeypatch.setattr(target, "MODEL", "gpt-6.2-sol")
    cost = target._cost(
        {
            "input_tokens": 1000,
            "cached_input_tokens": 400,
            "cache_write_tokens": 0,
            "output_tokens": 200,
        }
    )
    assert cost == pytest.approx(600 * 2e-6 + 400 * 1e-7 + 200 * 1e-5)
    monkeypatch.setattr(target, "MODEL", "unknown-sql-model")
    assert target._cost({"input_tokens": 100, "output_tokens": 50}) is None

    ref_files = sorted(p.name for p in target.TARGET.reference.rglob("*") if p.is_file())
    assert ref_files == ["README.md"]
    db = Db(build(tmp_path / "shop.sqlite"))
    try:
        ddl = db.schema()
        assert "--" not in ddl and "CREATE TABLE shop_meta" in ddl
    finally:
        db.close()
