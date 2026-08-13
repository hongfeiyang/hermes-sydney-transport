"""Directory-install shim for Hermes' native plugin loader."""

from .hermes_sydney_transport import register

__all__ = ["register"]
