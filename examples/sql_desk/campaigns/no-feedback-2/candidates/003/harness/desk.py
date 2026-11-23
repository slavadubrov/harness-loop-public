"""The SQL desk: answer a question about the shop's data with one SQL query.

``answer`` gets the question, the database (``db.schema()`` and ``db.query(sql)``, read
only) and the model (``model.complete(prompt)``). It returns one SELECT statement; the
evaluator runs it and compares the rows with the expected ones.
"""

import re

PROMPT = """Write one SQLite query that answers the question.

{schema}

Question: {question}

Before writing SQL, silently determine what one output row represents and which
columns the question asks to return. Return those columns in the requested order;
keep helper columns (such as ranks, sort keys, and join IDs) out of the final
projection unless requested. Check that joins do not multiply the entities or
facts being counted or summed: if combining independent one-to-many relationships,
aggregate each at the required grain before joining. If the question includes
entities with no matching activity, preserve them and count matching rows rather
than the NULL-extended row. Put requested ordering in the outermost query.

Reply with one read-only SQLite SELECT statement, optionally using CTEs, and no
explanation."""


def answer(question, db, model):
    reply = model.complete(PROMPT.format(schema=db.schema(), question=question))
    fenced = re.search(r"```(?:\w+)?\s*(.*?)```", reply, re.S)
    return (fenced.group(1) if fenced else reply).strip()
