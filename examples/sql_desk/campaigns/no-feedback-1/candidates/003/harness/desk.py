"""The SQL desk: answer a question about the shop's data with one SQL query.

``answer`` gets the question, the database (``db.schema()`` and ``db.query(sql)``, read
only) and the model (``model.complete(prompt)``). It returns one SELECT statement; the
evaluator runs it and compares the rows with the expected ones.
"""

import re

PROMPT = """Write one SQLite query that answers the question.

{schema}

Question: {question}

Check SQLite's value semantics before answering:
- For a whole-day or calendar-period filter on timestamps, use an inclusive start
  and an exclusive start of the next period. Don't compare a timestamp directly
  to a date-only string for equality. Use the question's reference date if given;
  use the latest stored date only when the question anchors the period to the data.
- For fractional ratios and percentages, promote an operand to REAL before
  division. Apply rounding to the final metric only if requested.
- Handle missing values according to the question: zero and NULL are not
  interchangeable, and NOT IN can reject every unmatched row if its subquery
  returns NULL. Prefer NOT EXISTS for a test that no matching row exists.

Reply with one read-only SELECT (CTEs allowed), SQL only."""


def answer(question, db, model):
    reply = model.complete(PROMPT.format(schema=db.schema(), question=question))
    fenced = re.search(r"```(?:\w+)?\s*(.*?)```", reply, re.S)
    return (fenced.group(1) if fenced else reply).strip()
