"""HTTP server for the ONI Companion API (contracts/api.md).

Later front ends (apps) can call start(config) or the views directly.
"""
from .service import Service, ServiceConfig, start  # noqa: F401
