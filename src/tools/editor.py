from pathlib import Path

# Maps file path -> stack of previous contents (for undo)
_history: dict[str, list[str]] = {}

MAX_VIEW_LINES = 200


def _save(path: str, content: str) -> None:
    _history.setdefault(path, []).append(content)


def _view(path: str, start_line: int | None, end_line: int | None) -> str:
    try:
        content = Path(path).read_text()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"

    lines = content.splitlines()
    total = len(lines)

    # Apply range if requested (1-indexed, inclusive)
    if start_line is not None or end_line is not None:
        lo = max((start_line or 1) - 1, 0)
        hi = min(end_line or total, total)
        lines = lines[lo:hi]
        offset = lo
    else:
        offset = 0

    truncated = len(lines) > MAX_VIEW_LINES
    if truncated:
        lines = lines[:MAX_VIEW_LINES]

    numbered = "\n".join(f"{i + offset + 1:4d} | {line}" for i, line in enumerate(lines))
    if truncated:
        numbered += f"\n[view truncated at {MAX_VIEW_LINES} lines — use start_line/end_line to read more]"
    return numbered


def _create(path: str, content: str) -> str:
    p = Path(path)
    if p.exists():
        return f"Error: {path} already exists. Use str_replace to edit it."
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _save(path, "")
        return f"Created {path}"
    except Exception as e:
        return f"Error creating {path}: {e}"


def _str_replace(path: str, old_str: str, new_str: str) -> str:
    try:
        content = Path(path).read_text()
    except FileNotFoundError:
        return f"Error: file not found: {path}"

    count = content.count(old_str)
    if count == 0:
        return f"Error: old_str not found in {path}"
    if count > 1:
        return (
            f"Error: old_str appears {count} times in {path} — "
            "add more surrounding context to make it unique"
        )

    _save(path, content)
    Path(path).write_text(content.replace(old_str, new_str, 1))
    return f"Replaced 1 occurrence in {path}"


def _insert(path: str, insert_line: int, new_str: str) -> str:
    try:
        content = Path(path).read_text()
    except FileNotFoundError:
        return f"Error: file not found: {path}"

    lines = content.splitlines(keepends=True)
    if not 0 <= insert_line <= len(lines):
        return f"Error: insert_line {insert_line} out of range (file has {len(lines)} lines)"

    _save(path, content)
    new_line = new_str if new_str.endswith("\n") else new_str + "\n"
    lines.insert(insert_line, new_line)
    Path(path).write_text("".join(lines))
    return f"Inserted at line {insert_line} in {path}"


def _undo(path: str) -> str:
    stack = _history.get(path)
    if not stack:
        return f"Error: no edit history for {path}"
    previous = stack.pop()
    Path(path).write_text(previous)
    return f"Undid last edit to {path}"


def text_editor(operation: str, path: str, **kwargs) -> str:
    dispatch = {
        "view":       lambda: _view(path, kwargs.get("start_line"), kwargs.get("end_line")),
        "create":     lambda: _create(path, kwargs.get("content", "")),
        "str_replace": lambda: _str_replace(path, kwargs["old_str"], kwargs["new_str"]),
        "insert":     lambda: _insert(path, kwargs["insert_line"], kwargs["new_str"]),
        "undo":       lambda: _undo(path),
    }
    handler = dispatch.get(operation)
    if not handler:
        return f"Error: unknown operation {operation!r}. Valid operations: {', '.join(dispatch)}"
    try:
        return handler()
    except KeyError as e:
        return f"Error: missing required parameter {e} for operation {operation!r}"


tools = [
    {
        "type": "function",
        "function": {
            "name": "text_editor",
            "description": (
                "Read, create, and edit text files. "
                "Prefer str_replace for edits — old_str must match exactly once in the file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["view", "create", "str_replace", "insert", "undo"],
                        "description": (
                            "view: read file (optional start_line/end_line). "
                            "create: create new file with content. "
                            "str_replace: replace a unique string with new_str. "
                            "insert: insert new_str before insert_line (0-indexed). "
                            "undo: revert the last edit."
                        )
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to the file"
                    },
                    "content": {
                        "type": "string",
                        "description": "Initial file content for 'create'"
                    },
                    "old_str": {
                        "type": "string",
                        "description": "Exact string to replace (must appear exactly once)"
                    },
                    "new_str": {
                        "type": "string",
                        "description": "Replacement text for str_replace, or inserted text for insert"
                    },
                    "insert_line": {
                        "type": "integer",
                        "description": "0-indexed line number before which to insert (for insert)"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to view, 1-indexed inclusive (for view)"
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to view, 1-indexed inclusive (for view)"
                    }
                },
                "required": ["operation", "path"]
            }
        }
    }
]

TOOL_MAPPING = {
    "text_editor": text_editor
}
