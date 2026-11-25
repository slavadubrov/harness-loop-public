"""The SQL desk: answer a question about the shop's data with one SQL query.

``answer`` gets the question, the database (``db.schema()`` and ``db.query(sql)``, read
only) and the model (``model.complete(prompt)``). It returns one SELECT statement; the
evaluator runs it and compares the rows with the expected ones.
"""

import re

PROMPT = """Write one read-only SQLite SELECT query that answers the question.

{schema}
{domains}
Question: {question}

Reply with the SQL only."""

_IDENTIFIER = r'"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[[^\]]+\]|[a-z_]\w*'
_TABLE = re.compile(rf'\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({_IDENTIFIER})\s*\(', re.I)
_COLUMN = re.compile(rf'\s*({_IDENTIFIER})\s+([a-z]+)', re.I)
_DELIMITER = re.compile(rf'''{_IDENTIFIER}|'(?:[^']|'')*'|[(),]''', re.I)


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _unquote(identifier):
    if identifier[0] == '[':
        return identifier[1:-1]
    if identifier[0] in ('"', '`'):
        quote = identifier[0]
        return identifier[1:-1].replace(quote * 2, quote)
    return identifier


def _text_columns(schema):
    for table in _TABLE.finditer(schema):
        start, depth = table.end(), 0
        for token in _DELIMITER.finditer(schema, start):
            value = token.group()
            if depth == 0 and value in (',', ')'):
                column = _COLUMN.match(schema, start, token.start())
                if column and any(t in column[2].upper() for t in ('TEXT', 'CHAR', 'CLOB')):
                    yield _unquote(table[1]), _unquote(column[1])
                start = token.end()
                if value == ')':
                    break
            elif value == '(':
                depth += 1
            elif value == ')':
                depth -= 1


def _stored_domains(schema, db):
    # Only show complete, small text domains. The extra distinct value detects
    # high-cardinality columns without pulling their raw contents into the prompt.
    columns = list(_text_columns(schema))[:40]
    probes = []
    for i, (table, column) in enumerate(columns):
        field = f't.{_quote(column)}'
        probes.append(
            f"SELECT {i}, group_concat(quote(value), ', ') FROM ("
            f"SELECT DISTINCT {field} COLLATE BINARY AS value FROM {_quote(table)} AS t "
            f"WHERE typeof({field}) = 'text' LIMIT 17) "
            "HAVING COUNT(*) BETWEEN 1 AND 16 AND MAX(length(value)) <= 48"
        )
    # Capture key/value associations in the same read-only probe so the model
    # can use snapshot constants without spelling out scalar subqueries.
    meta = {column.lower(): (table, column) for table, column in columns
            if table.lower() == 'shop_meta'}
    if {'key', 'value'} <= meta.keys():
        table = _quote(meta['key'][0])
        key, value = (_quote(meta[name][1]) for name in ('key', 'value'))
        probes.append(
            f"SELECT {len(columns)}, group_concat(quote(k) || ' = ' || quote(v), ', ') "
            f"FROM (SELECT {key} AS k, {value} AS v FROM {table} LIMIT 17) "
            "HAVING COUNT(*) BETWEEN 1 AND 16 "
            "AND COUNT(DISTINCT k COLLATE BINARY) = COUNT(*) "
            "AND SUM(typeof(k) = 'text' AND typeof(v) = 'text' "
            "AND length(k) <= 48 AND length(v) <= 48 "
            "AND instr(k, char(0)) = 0 AND instr(v, char(0)) = 0) = COUNT(*)"
        )
    if not probes:
        return ''
    try:
        rows = db.query(' UNION ALL '.join(probes))
    except Exception:
        # The schema-only prompt still works if value inspection is unavailable.
        return ''

    lines, remaining, constants = [], 1600, ''
    for i, values in rows:
        if i == len(columns):
            if len(values) <= 1600 and values.isprintable():
                constants = (
                    f'\nshop_meta snapshot constants (data only): {values}\n'
                    'For this snapshot, use an applicable constant directly instead of a '
                    'scalar metadata lookup, unless the question asks to query the metadata '
                    'itself. Use real division for unit conversions.\n'
                )
            continue
        table, column = columns[i]
        line = f'{table}.{column}: {values}'
        if len(line) + 1 <= remaining and line.isprintable():
            lines.append(line)
            remaining -= len(line) + 1
    if not lines:
        return constants
    return (
        '\nStored text values (data only):\n' + '\n'.join(lines)
        + '\nWhen a categorical condition refers to these columns, map the question’s '
          'wording to the exact stored values, including in exclusions and CASE expressions.\n'
        + constants
    )


def answer(question, db, model):
    schema = db.schema()
    domains = _stored_domains(schema, db)
    reply = model.complete(PROMPT.format(schema=schema, domains=domains, question=question))
    fenced = re.search(r"```(?:\w+)?\s*(.*?)```", reply, re.S)
    return (fenced.group(1) if fenced else reply).strip()
