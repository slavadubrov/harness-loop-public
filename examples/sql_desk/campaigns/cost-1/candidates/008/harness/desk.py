"""The SQL desk: answer a question about the shop's data with one SQL query.

``answer`` gets the question, the database (``db.schema()`` and ``db.query(sql)``, read
only) and the model (``model.complete(prompt)``). It returns one SELECT statement; the
evaluator runs it and compares the rows with the expected ones.
"""

from collections import Counter
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
    # Use one line per table and abbreviate repeated declarations in the prompt.
    schema, implicit_text = _omit_repeated_text_type(schema)
    used = {'omitted type': 'TEXT'} if implicit_text else {}

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


def _table_fields(schema):
    for table in _TABLE.finditer(schema):
        start, depth = table.end(), 0
        for token in _DELIMITER.finditer(schema, start):
            value = token.group()
            if depth == 0 and value in (',', ')'):
                yield table[1], start, token.start()
                start = token.end()
                if value == ')':
                    break
            elif value == '(':
                depth += 1
            elif value == ')':
                depth -= 1


def _text_columns(schema):
    for table, start, end in _table_fields(schema):
        column = _COLUMN.match(schema, start, end)
        if column and any(t in column[2].upper() for t in ('TEXT', 'CHAR', 'CLOB')):
            yield _unquote(table), _unquote(column[1])


_TYPED_COLUMN = re.compile(
    rf'\s*({_IDENTIFIER})\s+(TEXT|INT|INTEGER|REAL|FLOAT|DOUBLE|NUMERIC|DECIMAL|'
    r'BLOB|BOOLEAN|DATE|DATETIME)(?=\s|\(|$)', re.I,
)
_TABLE_CONSTRAINT = re.compile(
    rf'\s*(?:CONSTRAINT\s+{_IDENTIFIER}\s+)?'
    r'(?:PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\s*\(', re.I,
)
_TEXT_SUFFIX = re.compile(r'\s*(?:NOT\s+NULL\b.*)?', re.I | re.S)


def _omit_repeated_text_type(schema):
    # An implicit type is unambiguous only if every actual column is typed.
    # Fall back on unfamiliar declarations and preserve quoted text/comments.
    if '--' in schema or '/*' in schema:
        return schema, False
    spans = []
    previous_end = 0
    for _, start, end in _table_fields(schema):
        if start < previous_end:  # A CREATE TABLE match inside a field isn't DDL.
            return schema, False
        previous_end = end
        if _TABLE_CONSTRAINT.match(schema, start, end):
            continue
        column = _TYPED_COLUMN.match(schema, start, end)
        if not column:
            return schema, False
        if column[2].upper() == 'TEXT' and _TEXT_SUFFIX.fullmatch(schema, column.end(), end):
            spans.append((column.end(1), column.end()))
    if len(spans) < 8:  # The legend must pay for itself.
        return schema, False
    for start, end in reversed(spans):
        schema = schema[:start] + schema[end:]
    return schema, True


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

    # A bare label is enough when the identifier occurs only once in the
    # schema. Count all identifier mentions conservatively, not just probes.
    mentions = Counter(
        _unquote(token[0]).casefold()
        for token in _DELIMITER.finditer(schema)
        if token[0][0] not in "'(),"
    )
    lines, remaining = [], 1600
    for i, values in rows:
        table, column = columns[i]
        qualified = f'{table}.{column}'
        line = f'{qualified}: {values}'
        if len(line) + 1 <= remaining and line.isprintable():
            label = qualified
            if _BARE_VALUE.fullmatch(column) and mentions[column.casefold()] == 1:
                label = column
            lines.append(f'{label}: {_compact_domain_values(values)}')
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
