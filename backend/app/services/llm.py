"""Compatibility alias for app.ai.llm."""
import sys
from ..ai import llm as _implementation
sys.modules[__name__] = _implementation
