"""The SQL desk: answer a question about the shop's data with one SQL query.

``answer`` gets the question, the database (``db.schema()`` and ``db.query(sql)``, read
only) and the model (``model.complete(prompt)``). It returns one SELECT statement; the
evaluator runs it and compares the rows with the expected ones.
"""

import re

PROMPT = """Write one SQLite query that answers the question.

{schema}

Question: {question}

Before writing SQL, identify what one result row represents and which columns the
question asks to return. Check the grain of every measure after joining: if a
one-to-many join would repeat a row being counted or summed, aggregate at the
appropriate grain first, or use EXISTS if the related table is only a filter.
Do not use SUM(DISTINCT amount) to undo duplicated rows; different rows can have
the same amount. If entities with no matches must be included, preserve them and
count a non-null key from the matched side, not COUNT(*).

Apply ranking, limits, and ordering at the requested result grain, after any
required aggregation. Keep intermediate calculations and sort keys out of the
output unless requested. Check table and column names against the schema and
use SQLite syntax.

Reply with the SQL only."""


def answer(question, db, model):
    reply = model.complete(PROMPT.format(schema=db.schema(), question=question))
    fenced = re.search(r"```(?:\w+)?\s*(.*?)```", reply, re.S)
    return (fenced.group(1) if fenced else reply).strip()
