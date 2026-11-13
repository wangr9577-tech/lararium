"""Compatibility alias for app.ai.assistant_prompts."""
import sys
from ..ai import assistant_prompts as _implementation
sys.modules[__name__] = _implementation
