"""ScoutCTX is a model-neutral context and session framework for AI agents."""

__version__ = "0.2.0"

from .framework import ContextResult, ScoutCTX, build_context
from .models import Brief, BriefFile, ScanStats
from .providers import (
    ContextDocument,
    ContextProvider,
    ContextRequest,
    DirectoryProvider,
    ProviderRegistry,
    StaticProvider,
)
from .sessions import Session, SessionManager

__all__ = [
    "Brief",
    "BriefFile",
    "ContextDocument",
    "ContextProvider",
    "ContextRequest",
    "ContextResult",
    "DirectoryProvider",
    "ProviderRegistry",
    "ScanStats",
    "ScoutCTX",
    "Session",
    "SessionManager",
    "StaticProvider",
    "build_context",
]
