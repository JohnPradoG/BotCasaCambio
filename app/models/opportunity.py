"""Estados y niveles usados por las oportunidades (el motor llega en la Fase 2)."""

from __future__ import annotations

from enum import Enum


class OpportunityStatus(str, Enum):
    DETECTED = "DETECTED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
