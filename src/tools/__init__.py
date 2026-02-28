from .bash import tools as _bash_tools, TOOL_MAPPING as _bash_map, CATEGORY as _bash_cat
from .editor import tools as _editor_tools, TOOL_MAPPING as _editor_map, CATEGORY as _editor_cat
from .memory import tools as _memory_tools, TOOL_MAPPING as _memory_map, CATEGORY as _memory_cat
from .monarch import tools as _monarch_tools, TOOL_MAPPING as _monarch_map, CATEGORY as _monarch_cat

tools = _bash_tools + _editor_tools + _memory_tools + _monarch_tools
categories = [_bash_cat, _editor_cat, _memory_cat, _monarch_cat]

TOOL_MAPPING = {
    **_bash_map,
    **_editor_map,
    **_memory_map,
    **_monarch_map,
}

# Index schemas by name for fast lookup
_schemas: dict[str, dict] = {t["function"]["name"]: t for t in tools}


def get_tools(names: list[str]) -> tuple[list, dict]:
    """Return (tools_list, tool_mapping) containing only the named tools.

    Example:
        tools, TOOL_MAPPING = get_tools(["bash"])
    """
    unknown = set(names) - set(TOOL_MAPPING)
    if unknown:
        raise ValueError(f"Unknown tools: {unknown}. Available: {sorted(TOOL_MAPPING)}")
    return [_schemas[n] for n in names], {n: TOOL_MAPPING[n] for n in names}
