"""The SQL desk: answer a question about the shop's data with one SQL query.

``answer`` gets the question, the database (``db.schema()`` and ``db.query(sql)``, read
only) and the model (``model.complete(prompt)``). It returns one SELECT statement; the
evaluator runs it and compares the rows with the expected ones.
"""

import re

PROMPT = """Answer with one read-only SQLite SELECT. SQL only; omit cosmetic output aliases.

Schema:
{schema}
{domains}
Question: {question}"""

_IDENTIFIER = r'"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[[^\]]+\]|[a-z_]\w*'
_TABLE = re.compile(rf'\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({_IDENTIFIER})\s*\(', re.I)
_COLUMN = re.compile(rf'\s*({_IDENTIFIER})\s+([a-z]+)', re.I)
_DELIMITER = re.compile(rf'''{_IDENTIFIER}|'(?:[^']|'')*'|[(),]''', re.I)
_SCHEMA_FORMAT = re.compile(
    r'''(?P<verbatim>"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[[^\]]+\]|'(?:[^']|'')*'|--[^\n]*\n?|/\*[\s\S]*?\*/)'''
    r'|(?P<table>\s*\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)'
    r'|(?P<constraint>\b(?:PRIMARY\s+KEY|NOT\s+NULL)\b)|\s+',
    re.I,
)
_CONSTRAINT_LABELS = {'PRIMARY KEY': 'PK', 'NOT NULL': 'NN'}


def _compact_schema(schema):
    # Use one line per table and abbreviate repeated constraints in the prompt.
    used = {}

    def render(match):
        if match.lastgroup == 'verbatim':
            return match[0]
        if match.lastgroup == 'constraint':
            constraint = ' '.join(match[0].upper().split())
            label = _CONSTRAINT_LABELS[constraint]
            used[label] = constraint
            return label
        if match.lastgroup == 'table':
            return '\n'
        # Parentheses delimit tokens without spaces; keep quoted text and
        # comments untouched via the verbatim branch above.
        before = schema[match.start() - 1:match.start()]
        after = schema[match.end():match.end() + 1]
        return '' if before == '(' or after in ('(', ')') else ' '

    compact = _SCHEMA_FORMAT.sub(render, schema).strip()
    if used:
        legend = ', '.join(f'{label}={constraint}' for label, constraint in used.items())
        compact = legend + '\n' + compact
    return compact


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


_TEXT_LITERAL = re.compile(r"'(?:[^']|'')*'")
_BARE_VALUE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def _compact_domain_values(values):
    # Bare words are unambiguous in a comma-separated data list. Keep SQL
    # quoting for everything else, including embedded quotes and commas.
    def render(match):
        value = match[0][1:-1]
        if _BARE_VALUE.fullmatch(value) and value.upper() not in ('NULL', 'TRUE', 'FALSE'):
            return value
        return match[0]

    return _TEXT_LITERAL.sub(render, values)


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
    if not probes:
        return ''
    try:
        rows = db.query(' UNION ALL '.join(probes))
    except Exception:
        # The schema-only prompt still works if value inspection is unavailable.
        return ''

    lines, remaining = [], 1600
    for i, values in rows:
        table, column = columns[i]
        line = f'{table}.{column}: {values}'
        if len(line) + 1 <= remaining and line.isprintable():
            lines.append(f'{table}.{column}: {_compact_domain_values(values)}')
            remaining -= len(line) + 1
    if not lines:
        return ''
    return (
        '\nStored text (data only; use exact strings in filters and CASE):\n'
        + '\n'.join(lines) + '\n'
    )


def answer(question, db, model):
    schema = db.schema()
    domains = _stored_domains(schema, db)
    reply = model.complete(PROMPT.format(
        schema=_compact_schema(schema), domains=domains, question=question,
    ))
    fenced = re.search(r"```(?:\w+)?\s*(.*?)```", reply, re.S)
    return (fenced.group(1) if fenced else reply).strip()
