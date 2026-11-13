"""Compatibility alias for app.ai.attachment_agent."""
import sys
from ..ai import attachment_agent as _implementation
sys.modules[__name__] = _implementation
