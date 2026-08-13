"""Sydney Transport plugin public surface."""

from .bootstrap.registration import register
from .models.metadata import PLUGIN_VERSION

__version__ = PLUGIN_VERSION

__all__ = ["__version__", "register"]
