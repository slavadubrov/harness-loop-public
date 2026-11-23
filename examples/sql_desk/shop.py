"""The environment of the SQL desk: a shop's database, the read-only access a harness
gets to it, and the one model it may call.

The database is built from a fixed random seed, so every run and every reader gets the
same rows. It exposes raw DDL without comments plus ``shop_meta``, so column conventions
and enum codes live in the database itself rather than in documentation comments.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE shop_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    country     TEXT NOT NULL,
    segment     TEXT NOT NULL,
    signup_date TEXT NOT NULL
);
CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price_minor INTEGER NOT NULL
);
CREATE TABLE orders (
    id             INTEGER PRIMARY KEY,
    customer_id    INTEGER NOT NULL REFERENCES customers(id),
    status         TEXT NOT NULL,
    placed_at      TEXT NOT NULL,
    delivered_at   TEXT,
    shipping_minor INTEGER NOT NULL
);
CREATE TABLE order_items (
    order_id         INTEGER NOT NULL REFERENCES orders(id),
    product_id       INTEGER NOT NULL REFERENCES products(id),
    quantity         INTEGER NOT NULL,
    unit_price_minor INTEGER NOT NULL,
    PRIMARY KEY (order_id, product_id)
);
CREATE TABLE refunds (
    id           INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES orders(id),
    amount_minor INTEGER NOT NULL,
    reason       TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE tickets (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    order_id     INTEGER REFERENCES orders(id),
    topic        TEXT NOT NULL,
    opened_at    TEXT NOT NULL,
    resolved_at  TEXT,
    satisfaction INTEGER
);
"""
TODAY = date(2026, 6, 30)
FIRST = ["Ana", "Ben", "Chloe", "Dmitri", "Eva", "Farid", "Greta", "Hugo", "Ines", "Jonas"]
FIRST += ["Kira", "Liam", "Mona", "Nils", "Olga", "Pavel", "Quinn", "Rosa", "Sven", "Tara"]
LAST = ["Novak", "Ortiz", "Park", "Sokolov", "Lindqvist", "Haddad", "Meyer", "Laurent"]
LAST += ["Costa", "Becker", "Ivanova", "Walsh", "Jensen", "Kowalski", "Marin"]
COUNTRIES = ["DEU", "DEU", "DEU", "FRA", "FRA", "POL", "POL", "SWE", "ESP", "NLD", "USA", "USA"]
PRODUCTS = {
    "kitchen_dining": [
        "Ceramic teapot",
        "Knife set",
        "Espresso machine",
        "Cast-iron pan",
        "Kettle",
    ],
    "outdoor_sports": ["Bike helmet", "Carbon wheels", "Tent", "Trekking poles", "Camp stove"],
    "home_office": ["Standing desk", "Desk lamp", "Monitor arm", "Notebook set", "Office chair"],
    "audio_gear": [
        "Headphones",
        "Bluetooth speaker",
        "Turntable",
        "Studio microphone",
        "Earbuds",
    ],
    "home_decor": ["Wool blanket", "Linen tablecloth", "Floor lamp", "Wall clock", "Bookshelf"],
    "kids_toys": ["Wooden train", "Puzzle 1000", "Kite", "Building blocks", "Board game"],
}


def _iso_ts(d: date | None) -> str | None:
    return f"{d.isoformat()}T12:00:00Z" if d is not None else None


def build(path: Path | str) -> Path:
    """Write the shop's database to ``path`` and return it. The same file every time."""
    path = Path(path)
    path.unlink(missing_ok=True)
    rng = random.Random(20261116)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO shop_meta VALUES (?,?)",
        [
            ("currency", "USD"),
            ("minor_units_per_dollar", "100"),
            ("as_of_date", TODAY.isoformat()),
        ],
    )

    def day(lo: int, hi: int) -> date:
        return TODAY - timedelta(days=rng.randint(lo, hi))

    names = rng.sample([(f, s) for f in FIRST for s in LAST], 60)
    for i, (first, last) in enumerate(names, 1):
        segment = rng.choices(["consumer_direct", "b2b_account", "reseller_partner"], [6, 3, 1])[0]
        email = f"{first}.{last}@example.com".lower()
        row = (
            i,
            f"{first} {last}",
            email,
            rng.choice(COUNTRIES),
            segment,
            day(200, 900).isoformat(),
        )
        con.execute("INSERT INTO customers VALUES (?,?,?,?,?,?)", row)
    prices = {}
    for pid, (category, name) in enumerate(((c, n) for c, ns in PRODUCTS.items() for n in ns), 1):
        prices[pid] = rng.choice([1500, 2400, 3900, 4800, 6500, 8900, 12900, 18900, 35000, 42000])
        con.execute("INSERT INTO products VALUES (?,?,?,?)", (pid, name, category, prices[pid]))
    for oid in range(1, 321):
        placed = day(3, 180)
        statuses = ["delivered_complete", "in_transit", "pending_payment", "canceled"]
        status = rng.choices(statuses, [70, 12, 8, 10])[0]
        delivered = (
            placed + timedelta(days=rng.randint(2, 9)) if status == "delivered_complete" else None
        )
        if delivered and delivered > TODAY:
            status, delivered = "in_transit", None
        buyer = rng.randint(1, 60) if rng.random() < 0.8 else rng.randint(1, 12)  # some buy often
        row = (oid, buyer, status, _iso_ts(placed), _iso_ts(delivered))
        con.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)", (*row, rng.choice([0, 0, 490, 990])))
        for pid in rng.sample(sorted(prices), rng.choices([1, 2, 3, 4], [5, 3, 2, 1])[0]):
            paid = round(prices[pid] * rng.choice([1, 1, 1, 0.9, 0.8]))
            con.execute(
                "INSERT INTO order_items VALUES (?,?,?,?)", (oid, pid, rng.randint(1, 3), paid)
            )
    delivered = [
        r[0] for r in con.execute("SELECT id FROM orders WHERE status = 'delivered_complete'")
    ]
    for rid, oid in enumerate(rng.sample(delivered, 44), 1):
        total = con.execute(
            "SELECT SUM(quantity * unit_price_minor) FROM order_items WHERE order_id = ?", (oid,)
        ).fetchone()[0]
        amount = total if rng.random() < 0.6 else max(500, round(total * rng.choice([0.25, 0.5])))
        reason = rng.choice(
            ["item_damaged", "item_damaged", "arrived_late", "wrong_item_sent", "changed_mind"]
        )
        when = date.fromisoformat(
            con.execute("SELECT date(delivered_at) FROM orders WHERE id = ?", (oid,)).fetchone()[0]
        ) + timedelta(days=rng.randint(1, 20))
        row = (rid, oid, amount, reason, _iso_ts(min(when, TODAY)))
        con.execute("INSERT INTO refunds VALUES (?,?,?,?,?)", row)
    for tid in range(1, 91):
        about = rng.choice(delivered) if rng.random() < 0.7 else None
        who = (
            con.execute("SELECT customer_id FROM orders WHERE id = ?", (about,)).fetchone()[0]
            if about
            else rng.randint(1, 60)
        )
        opened = day(1, 150)
        done = opened + timedelta(days=rng.randint(0, 6)) if rng.random() < 0.8 else None
        done = done if done and done <= TODAY else None
        score = rng.randint(1, 5) if done and rng.random() < 0.75 else None
        topic = rng.choice(
            ["delivery_delay", "refund_request", "product_issue", "account_help", "billing_invoice"]
        )
        row = (tid, who, about, topic, _iso_ts(opened), _iso_ts(done), score)
        con.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?,?)", row)
    con.commit()
    con.close()
    return path


class QueryError(Exception):
    """A statement that SQLite refused or could not run."""


READS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
READS |= {sqlite3.SQLITE_RECURSIVE}


class Db:
    """What a harness may do with the database: read the schema and run SELECT statements.
    Every statement is recorded, and so is every attempt to change the data."""

    def __init__(self, path: Path | str, max_rows: int = 200) -> None:
        self.log: list[dict] = []  # {"name": "query" | "write", "sql": ..., "ok": ...}
        self.max_rows = max_rows
        self._con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self._con.set_authorizer(self._allow)
        self._denied = False

    def _allow(self, action: int, *_: object) -> int:
        if action in READS:
            return sqlite3.SQLITE_OK
        self._denied = True
        return sqlite3.SQLITE_DENY

    def schema(self) -> str:
        """The CREATE TABLE statements from sqlite_master, without comments."""
        rows = self._con.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY rowid"
        ).fetchall()
        return ";\n\n".join(r[0] for r in rows) + ";"

    def query(self, sql: str) -> list[tuple]:
        """Run one SELECT statement and return at most ``max_rows`` rows. Raises
        QueryError with SQLite's message when the statement does not run."""
        self._denied = False
        try:
            rows = self._con.execute(sql).fetchmany(self.max_rows)
        except (sqlite3.Error, sqlite3.Warning) as exc:
            self.log.append({"name": "write" if self._denied else "query", "sql": sql, "ok": False})
            raise QueryError(str(exc)) from None
        self.log.append({"name": "query", "sql": sql, "ok": True})
        return rows

    def close(self) -> None:
        self._con.close()


class Model:
    """The one model a harness may call, behind an OpenAI-compatible endpoint. It counts
    its calls and tokens, and refuses more than ``max_calls`` for one question."""

    def __init__(
        self,
        url: str,
        model: str,
        seed: int,
        *,
        api_key: str = "",
        reasoning_effort: str = "low",
        max_calls: int = 6,
        deadline: float | None = None,
    ) -> None:
        self.url = url
        self.model = model
        self.seed = seed
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self.max_calls = max_calls
        self.deadline = deadline
        self.calls = 0
        self.input_tokens = 0
        self.cached_input_tokens = 0
        self.cache_write_tokens = 0
        self.output_tokens = 0
        self.reasoning_tokens = 0

    def complete(self, prompt: str, max_tokens: int = 1024) -> str:
        """The model's reply to one prompt."""
        if self.calls >= self.max_calls:
            raise RuntimeError(f"more than {self.max_calls} model calls for one question")
        if self.deadline is not None and time.perf_counter() > self.deadline:
            raise TimeoutError("question time limit exceeded")
        body: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": max_tokens,
            "seed": self.seed * 100 + self.calls,  # a repeated prompt gets a new sample
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        self.calls += 1
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key or 'local'}",
        }
        payload = json.dumps(body).encode()
        for attempt in range(3):
            if self.deadline is not None and time.perf_counter() > self.deadline:
                raise TimeoutError("question time limit exceeded")
            request = urllib.request.Request(
                self.url.rstrip("/") + "/chat/completions", payload, headers
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    reply = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise RuntimeError(f"HTTP {exc.code} from model endpoint") from None
            except urllib.error.URLError as exc:
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise RuntimeError(f"connection error: {exc.reason}") from None
        usage = reply.get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        self.input_tokens += usage.get("prompt_tokens", 0) or 0
        self.cached_input_tokens += prompt_details.get("cached_tokens", 0) or 0
        self.cache_write_tokens += prompt_details.get("cache_write_tokens", 0) or 0
        self.output_tokens += usage.get("completion_tokens", 0) or 0
        self.reasoning_tokens += completion_details.get("reasoning_tokens", 0) or 0
        return reply["choices"][0]["message"]["content"] or ""
