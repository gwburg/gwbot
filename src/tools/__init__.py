import os

from .bash import tools as _bash_tools, TOOL_MAPPING as _bash_map, CATEGORY as _bash_cat, TAG as _bash_tag
from .editor import tools as _editor_tools, TOOL_MAPPING as _editor_map, CATEGORY as _editor_cat, TAG as _editor_tag
from .memory import tools as _memory_tools, TOOL_MAPPING as _memory_map, CATEGORY as _memory_cat, TAG as _memory_tag
from .scheduler import tools as _scheduler_tools, TOOL_MAPPING as _scheduler_map, CATEGORY as _scheduler_cat, TAG as _scheduler_tag

_modules = [
    (_bash_tools, _bash_map, _bash_cat, _bash_tag),
    (_editor_tools, _editor_map, _editor_cat, _editor_tag),
    (_memory_tools, _memory_map, _memory_cat, _memory_tag),
    (_scheduler_tools, _scheduler_map, _scheduler_cat, _scheduler_tag),
]

if os.getenv("MONARCH_TOKEN"):
    from .monarch import tools as _monarch_tools, TOOL_MAPPING as _monarch_map, CATEGORY as _monarch_cat, TAG as _monarch_tag
    _modules.append((_monarch_tools, _monarch_map, _monarch_cat, _monarch_tag))

tools = [t for ts, _, _, _ in _modules for t in ts]
categories = [cat for _, _, cat, _ in _modules]

TOOL_MAPPING = {}
for _, mapping, _, _ in _modules:
    TOOL_MAPPING.update(mapping)

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
