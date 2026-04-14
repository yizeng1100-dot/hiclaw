"""Tool registry package.

Importing this module registers every tool module side-effect-ly, so
``openai_tools_spec()`` reflects the full set as soon as the package
is imported.
"""

from custom.chatbot.tools.base import (
    Tool,
    dumps,
    openai_tools_spec,
    register,
    run_tool,
)

# Import each tool module so its @register() calls fire.
from custom.chatbot.tools import agents as _agents  # noqa: F401
from custom.chatbot.tools import launch as _launch  # noqa: F401
from custom.chatbot.tools import schedules as _schedules  # noqa: F401
from custom.chatbot.tools import skills as _skills  # noqa: F401
from custom.chatbot.tools import tasks as _tasks  # noqa: F401

__all__ = ['Tool', 'register', 'openai_tools_spec', 'run_tool', 'dumps']
