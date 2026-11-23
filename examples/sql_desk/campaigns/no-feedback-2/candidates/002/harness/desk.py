"""The SQL desk: answer a question about the shop's data with one SQL query.

``answer`` gets the question, the database (``db.schema()`` and ``db.query(sql)``, read
only) and the model (``model.complete(prompt)``). It returns one SELECT statement; the
evaluator runs it and compares the rows with the expected ones.
"""

import re

PROMPT = """Write one read-only SQLite SELECT that answers the question.

{schema}

Question: {question}

Reply with the SQL only."""

_SQL_TOKEN = re.compile(
    r"""--[^\n]*|/\*.*?(?:\*/|\Z)|'(?:''|[^'])*'|"(?:""|[^"])*"|"""
    r"""`(?:``|[^`])*`|\[[^\]]*\]|[A-Za-z_][\w$]*|[^\s]""",
    re.S,
)


def _candidate(reply):
    fenced = re.search(r"```(?:sql(?:ite)?\b)?\s*(.*?)```", reply, re.I | re.S)
    sql = (fenced.group(1) if fenced else reply).strip()
    tokens = [m for m in _SQL_TOKEN.finditer(sql) if not m[0].startswith(("--", "/*"))]
    if tokens and tokens[-1][0] == ";":
        tokens.pop()
    if not tokens or tokens[0][0].upper() not in ("SELECT", "WITH"):
        raise ValueError("Expected a SELECT, optionally starting with WITH.")

    # Keep the candidate inside the probe's subquery, even for malformed replies.
    depth = 0
    for match in tokens:
        token = match[0]
        if token in (";", "'", '"', "`", "["):
            raise ValueError("Expected one statement with properly quoted SQL tokens.")
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
            if depth < 0:
                break
    if depth != 0:
        raise ValueError("Unbalanced parentheses in the SELECT.")
    return sql[tokens[0].start():tokens[-1].end()]


def _check(reply, db):
    sql = _candidate(reply)
    # Resolve names and compile the query without retrieving its result rows.
    db.query("SELECT * FROM (\n" + sql + "\n) AS proposed_answer LIMIT 0")
    return sql


def answer(question, db, model):
    prompt = PROMPT.format(schema=db.schema(), question=question)
    reply = model.complete(prompt)
    try:
        return _check(reply, db)
    except Exception as error:
        reason = str(error)[:400]

    repair = model.complete(
        prompt + "\n\nThe first attempt was:\n" + reply
        + "\n\nThe SELECT check rejected it: " + reason
        + "\nFix the problem while still answering the original question. Reply with SQL only."
    )
    try:
        return _check(repair, db)
    except Exception:
        return "SELECT NULL WHERE 0"
