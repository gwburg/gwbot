from .bash import tools as _bash_tools, TOOL_MAPPING as _bash_map
from .editor import tools as _editor_tools, TOOL_MAPPING as _editor_map
from .monarch import tools as _monarch_tools, TOOL_MAPPING as _monarch_map

tools = _bash_tools + _editor_tools + _monarch_tools

TOOL_MAPPING = {
    **_bash_map,
    **_editor_map,
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
