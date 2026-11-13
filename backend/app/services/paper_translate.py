"""Compatibility alias for app.ai.paper_translate."""
import sys
from ..ai import paper_translate as _implementation
sys.modules[__name__] = _implementation
