"""Minimal, format-preserving editing of Cryptic textparser files (.powers, .villain, .nd, ...).

These files are nested `Keyword { Field value ... }` blocks. We never re-serialize: every edit
splices the original text, so untouched lines stay byte-identical for clean diffs.
"""
import re
from dataclasses import dataclass, field


@dataclass
class Block:
    start: int          # start of the header line
    open: int           # index of "{"
    close: int          # index of matching "}"
    keyword: str
    header: str
    children: list = field(default_factory=list)

    @property
    def end(self):
        return self.close + 1


def _header_before(text, brace):
    """The header for a block is the text before '{' on its line, or the previous non-blank line."""
    line_start = text.rfind("\n", 0, brace) + 1
    same_line = text[line_start:brace].strip()
    if same_line:
        return line_start, same_line
    j = line_start - 1
    while j > 0:
        prev_start = text.rfind("\n", 0, j) + 1
        prev = text[prev_start:j].strip()
        if prev:
            return prev_start, prev
        j = prev_start - 1
    return line_start, ""


def parse(text):
    """Return the top-level blocks of text, each with nested children."""
    roots, stack = [], []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "/" and text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl < 0 else nl
            continue
        elif c == "/" and text.startswith("/*", i):
            e = text.find("*/", i + 2)
            i = n if e < 0 else e + 2
            continue
        elif c == "{":
            start, header = _header_before(text, i)
            kw = header.split()[0] if header else ""
            stack.append(Block(start, i, -1, kw, header))
        elif c == "}" and stack:
            b = stack.pop()
            b.close = i
            (stack[-1].children if stack else roots).append(b)
        i += 1
    return roots


def _own_lines(text, block):
    """(abs_start, abs_end, line) for lines directly inside block (not inside child blocks)."""
    pos = text.find("\n", block.open) + 1
    child_spans = [(c.start, c.end) for c in block.children]
    while 0 < pos < block.close:
        nl = text.find("\n", pos)
        nl = block.close if nl < 0 or nl > block.close else nl
        if not any(s <= pos < e for s, e in child_spans):
            yield pos, nl, text[pos:nl]
        pos = nl + 1


def field_value(text, block, name):
    for _s, _e, line in _own_lines(text, block):
        m = re.match(r"\s*(\S+)\s+(.*?)\s*$", line)
        if m and m.group(1) == name:
            return m.group(2).strip('"')
    return None


def block_name(text, block, fields=("FullName", "Name")):
    for f in fields:
        v = field_value(text, block, f)
        if v:
            return v
    return None


def find_block(text, name, fields=("FullName", "Name"), blocks=None):
    """Depth-first search for a block whose FullName/Name equals name."""
    for b in (parse(text) if blocks is None else blocks):
        if block_name(text, b, fields) == name:
            return b
        hit = find_block(text, name, fields, b.children)
        if hit:
            return hit
    return None


def own_field_names(text, block):
    names = []
    for _s, _e, line in _own_lines(text, block):
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\b", line)
        if m:
            names.append(m.group(1))
    return names


def set_field(block_text, name, value, quote=None):
    """Set a field on the outermost block of block_text. Returns (new_text, replaced: bool)."""
    root = parse(block_text)[0]
    if quote is None:
        quote = bool(re.search(r"[\s,'\-!?]", str(value))) and not re.fullmatch(r"[-\d., ]+", str(value))
    rendered = f'"{value}"' if quote else str(value)
    indent = None
    for s, e, line in _own_lines(block_text, root):
        m = re.match(r"(\s*)(\S+)(\s+)", line)
        if not m:
            continue
        indent = indent if indent is not None else m.group(1)
        if m.group(2) == name:
            new_line = f"{m.group(1)}{name}{m.group(3)}{rendered}"
            return block_text[:s] + new_line + block_text[e:], True
    indent = indent if indent is not None else "\t"
    close_line = block_text.rfind("\n", 0, root.close) + 1
    insert = f"{indent}{name} {rendered}\n"
    return block_text[:close_line] + insert + block_text[close_line:], False


def child_blocks(block_text, keyword=None):
    root = parse(block_text)[0]
    return [c for c in root.children if keyword is None or c.keyword == keyword]


def replace_child(block_text, child, new_child_text):
    return block_text[:child.start] + new_child_text + block_text[child.end:]


def token_pattern(keys):
    keys = sorted(keys, key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z0-9_.])(" + "|".join(re.escape(k) for k in keys) + r")(?![A-Za-z0-9_.])")


def replace_tokens(text, mapping):
    """Whole-identifier replacement. Dots count as identifier chars, so 'A.B' never matches inside 'A.B.C'."""
    if not mapping:
        return text, 0
    pat = token_pattern(mapping)
    count = 0

    def sub(m):
        nonlocal count
        count += 1
        return mapping[m.group(1)]
    return pat.sub(sub, text), count


def find_tokens(text, tokens):
    if not tokens:
        return []
    pat = token_pattern(tokens)
    hits = []
    for m in pat.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        hits.append((m.group(1), line_no))
    return hits
