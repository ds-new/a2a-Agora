"""Minimal, spec-faithful A2A v1.0 implementation (JSON-RPC 2.0 binding).

Field names follow the canonical ``specification/a2a.proto`` in its ProtoJSON
(camelCase) form; method names are the v1.0 PascalCase ones (``SendMessage``,
``GetTask`` ...). Source: github.com/a2aproject/A2A @ 5f931b8.
"""

from .types import *  # noqa: F401,F403
