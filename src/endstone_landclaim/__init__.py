# Make both names available for old entry points and new code.
from .index_plugin import MyPlugin as LandClaimPlugin
from .index_plugin import MyPlugin  # optional: direct access as MyPlugin

__all__ = ["index_plugin"]