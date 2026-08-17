"""Shared middleware helpers for building DeepAgents subagents.

`create_deep_agent` (and every subagent it builds) attaches a default
`FilesystemMiddleware` automatically -- `ls`, `read_file`, `write_file`,
`edit_file`, `delete`, `glob`, `grep`, `execute` -- bound to an in-memory
virtual filesystem that is empty and unrelated to both the real Colab
filesystem and this harness's SQLite-backed index. Observed live: a
Cartographer subagent tried `ls /`, `ls /workspace`, and a recursive glob
before ever calling the index tools it was actually given, found nothing
(the virtual FS is empty), and wrote "no target code discoverable" for
every section instead of using get_function_body/find_symbol/etc.

The framework requires `read_file` to always be present in a
`FilesystemMiddleware`'s tool list -- it cannot be fully suppressed -- so
this shrinks it to just that one tool, removing the ones (`ls`, `glob`,
`grep`, ...) that most invite "explore the filesystem" behavior.
"""
from __future__ import annotations

from deepagents.middleware.filesystem import FilesystemMiddleware

NO_FILESYSTEM_EXPLORATION_WARNING = """\
You have no real filesystem access. Any read_file-shaped tool you might \
see is bound to an empty, in-memory virtual filesystem completely \
unrelated to the actual target -- it will never return real code, no \
matter what path you try. Do not attempt to explore, list, or read files \
directly. The only way to read the target's code is through the specific \
tools named above.\
"""


def minimal_filesystem_middleware() -> FilesystemMiddleware:
    """A FilesystemMiddleware exposing only the one tool the framework
    requires, instead of the full default set."""
    return FilesystemMiddleware(tools=["read_file"])
