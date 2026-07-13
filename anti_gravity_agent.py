#!/usr/bin/env python3
"""
anti_gravity_agent.py
=====================

Core template for the **Anti-Gravity Agent** — an independent, production-oriented
computation agent that inherits the battle-tested patterns proven in the
GTOS Dataverse Automation project.

Patterns inherited from GTOS (see ANTI_GRAVITY_STRATEGIC_PLAN.md):
  * Token protection      -> credentials are NEVER stored in session headers or
                             emitted to logs; they are injected only at request
                             execution time and masked everywhere else.
  * Smart exponential      -> fixed sleep() calls are replaced with an adaptive
    back-off               back-off (initial 10s, capped at 60s, max 8 retries)
                             that detects "locked" / rate-limited states.
  * Specific exceptions    -> a 5-type exception hierarchy replaces bare
                             Exception, so callers can catch precisely.
  * Env-based config       -> every knob is an environment variable; nothing is
                             hard-coded.
  * Structured logging     -> a logging scaffold with automatic token masking.

This module is intentionally dependency-light (standard library only) so it can
be dropped into any environment and executed directly:

    python anti_gravity_agent.py --demo

Author : Anti-Gravity Engineering (bootstrapped from GTOS patterns)
Status : Reference template — Phase 1 (Foundation)
License : MIT
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


# ---------------------------------------------------------------------------
# 1. CONFIGURATION MANAGEMENT  (env-based, nothing hard-coded)
# ---------------------------------------------------------------------------
class Config:
    """Central configuration, sourced entirely from environment variables.

    Mirrors the GTOS approach: safe defaults, overridable per environment,
    zero secrets baked into source.
    """

    # --- Computation settings ---
    COMPUTATION_TIMEOUT: int = int(os.getenv("AG_COMPUTATION_TIMEOUT", "300"))
    BATCH_SIZE: int = int(os.getenv("AG_BATCH_SIZE", "1000"))

    # --- Retry / back-off settings ---
    MAX_RETRIES: int = int(os.getenv("AG_MAX_RETRIES", "8"))
    INITIAL_DELAY: int = int(os.getenv("AG_INITIAL_DELAY", "10"))   # seconds
    MAX_DELAY: int = int(os.getenv("AG_MAX_DELAY", "60"))           # seconds

    # --- HTTP / integration settings ---
    REQUEST_TIMEOUT: int = int(os.getenv("AG_REQUEST_TIMEOUT", "30"))
    GTOS_DATAVERSE_URL: Optional[str] = os.getenv("GTOS_DATAVERSE_URL")
    API_VERSION: str = os.getenv("AG_API_VERSION", "v1")

    # --- Logging settings ---
    LOG_LEVEL: str = os.getenv("AG_LOG_LEVEL", "INFO")

    @classmethod
    def as_dict(cls) -> Dict[str, Any]:
        return {
            k: getattr(cls, k)
            for k in dir(cls)
            if k.isupper() and not k.startswith("_")
        }


# ---------------------------------------------------------------------------
# 2. SECURE LOGGING  (automatic token / secret masking)
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
    re.compile(r"((?:client_secret|password|token|api[_-]?key)\s*[=:]\s*)\S+",
               re.IGNORECASE),
]


class SecretMaskingFilter(logging.Filter):
    """Redacts anything that looks like a credential before it hits a handler."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if isinstance(record.msg, str):
            record.msg = self._mask(record.msg)
        # Only touch positional tuple args. A single mapping arg (dict) is a
        # special logging convention for %(name)s formatting — leave it intact.
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._mask(a) if isinstance(a, str) else a for a in record.args
            )
        return True

    @staticmethod
    def _mask(text: str) -> str:
        for pat in _SECRET_PATTERNS:
            text = pat.sub(lambda m: f"{m.group(1)}***REDACTED***", text)
        return text


def build_logger(name: str = "anti_gravity") -> logging.Logger:
    logger_ = logging.getLogger(name)
    if logger_.handlers:  # already configured
        return logger_
    logger_.setLevel(getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO))
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    handler.addFilter(SecretMaskingFilter())
    logger_.addHandler(handler)
    logger_.propagate = False
    return logger_


logger = build_logger()


# ---------------------------------------------------------------------------
# 3. EXCEPTION HIERARCHY  (5 specific types, GTOS-style)
# ---------------------------------------------------------------------------
class AntiGravityError(Exception):
    """Base exception for all Anti-Gravity errors."""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        base = self.message
        if self.status_code is not None:
            base = f"[{self.status_code}] {base}"
        return base


class ComputationAuthError(AntiGravityError):
    """Authentication / authorization failures."""


class ComputationLockedError(AntiGravityError):
    """Resource is locked (in use, batch processing, or rate-limited)."""


class ComputationValidationError(AntiGravityError):
    """Input validation failures."""


class ComputationTimeoutError(AntiGravityError):
    """Computation exceeded its allotted time."""


class ComputationIntegrityError(AntiGravityError):
    """Data integrity violations."""


class ExhaustedRetriesError(AntiGravityError):
    """Raised when the retry manager gives up."""


# ---------------------------------------------------------------------------
# 4. SMART RETRY MANAGER  (exponential back-off, 10s -> 60s cap, max 8)
# ---------------------------------------------------------------------------
class SmartRetryManager:
    """Adaptive retry with capped linear/exponential back-off.

    Only *retryable* errors (locks / rate limits) trigger a wait; everything
    else propagates immediately. This is what gave GTOS its 3-7x speed-up over
    fixed sleeps.
    """

    def __init__(self,
                 initial_delay: int = Config.INITIAL_DELAY,
                 max_delay: int = Config.MAX_DELAY,
                 max_retries: int = Config.MAX_RETRIES,
                 sleep_fn: Callable[[float], None] = time.sleep):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self._sleep = sleep_fn

    def _delay_for(self, attempt: int) -> int:
        # attempt is 0-indexed: 10s, 20s, 30s, ... capped at max_delay
        return min(self.initial_delay * (attempt + 1), self.max_delay)

    def execute_with_retry(self, operation: Callable[..., Any],
                           *args: Any, **kwargs: Any) -> Any:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                return operation(*args, **kwargs)
            except ComputationLockedError as exc:
                last_error = exc
                delay = self._delay_for(attempt)
                logger.warning(
                    "Locked (attempt %d/%d). Backing off %ds...",
                    attempt + 1, self.max_retries, delay,
                )
                if attempt < self.max_retries - 1:
                    self._sleep(delay)
        raise ExhaustedRetriesError(
            f"Max retries ({self.max_retries}) exceeded",
            details={"last_error": str(last_error)},
        )


# ---------------------------------------------------------------------------
# 5. SECURE CLIENT  (token never in headers/logs; injected at call time)
# ---------------------------------------------------------------------------
@dataclass
class Credentials:
    client_id: Optional[str] = None
    client_secret: Optional[str] = field(default=None, repr=False)  # never repr'd
    token: Optional[str] = field(default=None, repr=False)


class AntiGravityClient:
    """Thin, security-first client scaffold.

    The token lives ONLY in a private attribute and is added to a request's
    headers at the moment of execution — never persisted on a session object,
    never logged.
    """

    def __init__(self, credentials: Optional[Credentials] = None,
                 retry_manager: Optional[SmartRetryManager] = None):
        self._creds = credentials or Credentials()
        self._token: Optional[str] = self._creds.token
        self._retry = retry_manager or SmartRetryManager()

    # -- auth -------------------------------------------------------------
    def authenticate(self) -> None:
        """Placeholder auth flow. Real impl would call MSAL / OAuth here and
        cache the token (force_refresh=False), exactly like GTOS."""
        if not (self._creds.client_id and self._creds.client_secret):
            # In real life you might fall back to interactive/device-code auth.
            logger.info("No client credentials supplied; using anonymous mode.")
            self._token = self._token or "anonymous"
            return
        # Simulated token acquisition (do NOT log the secret/token).
        self._token = f"tok-{uuid.uuid4().hex}"
        logger.info("Authenticated client_id=%s (token acquired, masked).",
                    self._creds.client_id)

    def _headers(self) -> Dict[str, str]:
        """Build headers WITH the token — called only at execution time."""
        if not self._token:
            raise ComputationAuthError("Client is not authenticated")
        return {
            "Authorization": f"Bearer {self._token}",
            "X-Request-ID": str(uuid.uuid4()),
            "Accept": "application/json",
        }

    def execute(self, operation: Callable[[Dict[str, str]], Any]) -> Any:
        """Run `operation(headers)` under retry protection."""
        def _run() -> Any:
            headers = self._headers()  # token injected here, and only here
            return operation(headers)
        return self._retry.execute_with_retry(_run)


# ---------------------------------------------------------------------------
# 6. CORE COMPUTATION ENGINE  (illustrative gravity/field maths)
# ---------------------------------------------------------------------------
GRAVITATIONAL_CONSTANT = 6.674_30e-11  # m^3 kg^-1 s^-2


def validate_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise ComputationValidationError(
            f"{name} must be numeric, got {type(value).__name__}")
    if value <= 0:
        raise ComputationValidationError(f"{name} must be > 0, got {value}")
    return float(value)


class GravityEngine:
    """Deterministic core engine. No I/O, fully unit-testable."""

    def field_strength(self, mass_kg: float, radius_m: float) -> float:
        """Newtonian gravitational field strength g = G*M / r^2 (m/s^2)."""
        mass_kg = validate_positive("mass_kg", mass_kg)
        radius_m = validate_positive("radius_m", radius_m)
        return GRAVITATIONAL_CONSTANT * mass_kg / (radius_m ** 2)

    def anti_gravity_thrust(self, mass_kg: float, radius_m: float,
                            efficiency: float = 1.0) -> float:
        """Self-lift thrust (N) for a body of mass `mass_kg` against its OWN
        surface gravity at `radius_m`.

        F = m * g_self * efficiency, where g_self = G*m / r^2.
        (efficiency in (0, 1]).
        """
        if not 0 < efficiency <= 1:
            raise ComputationValidationError(
                f"efficiency must be in (0, 1], got {efficiency}")
        g = self.field_strength(mass_kg, radius_m)
        return validate_positive("mass_kg", mass_kg) * g * efficiency

    def hover_thrust(self, payload_mass_kg: float, ambient_g: float,
                     efficiency: float = 1.0) -> float:
        """Thrust (N) to hover a payload in a given ambient field.

        F = m * g_ambient / efficiency  (lower efficiency => more thrust).
        """
        payload_mass_kg = validate_positive("payload_mass_kg", payload_mass_kg)
        ambient_g = validate_positive("ambient_g", ambient_g)
        if not 0 < efficiency <= 1:
            raise ComputationValidationError(
                f"efficiency must be in (0, 1], got {efficiency}")
        return payload_mass_kg * ambient_g / efficiency


# ---------------------------------------------------------------------------
# 7. AGENT FACADE  (wires engine + client + retry together)
# ---------------------------------------------------------------------------
class AntiGravityAgent:
    def __init__(self, credentials: Optional[Credentials] = None):
        self.engine = GravityEngine()
        self.client = AntiGravityClient(credentials)

    def bootstrap(self) -> None:
        self.client.authenticate()
        logger.info("Anti-Gravity Agent ready. Config=%s", Config.as_dict())

    def compute(self, mass_kg: float, radius_m: float,
                efficiency: float = 1.0) -> Dict[str, Any]:
        computation_id = str(uuid.uuid4())
        g = self.engine.field_strength(mass_kg, radius_m)
        thrust = self.engine.anti_gravity_thrust(mass_kg, radius_m, efficiency)
        result = {
            "computation_id": computation_id,
            "inputs": {"mass_kg": mass_kg, "radius_m": radius_m,
                       "efficiency": efficiency},
            "field_strength_m_s2": g,
            "anti_gravity_thrust_N": thrust,
        }
        logger.info("Computed %s: g=%.6e thrust=%.6e",
                    computation_id, g, thrust)
        return result


# ---------------------------------------------------------------------------
# 8. CLI / DEMO ENTRY POINT
# ---------------------------------------------------------------------------
def _demo() -> int:
    logger.info("=== Anti-Gravity Agent demo ===")
    agent = AntiGravityAgent(
        Credentials(client_id=os.getenv("GTOS_CLIENT_ID"),
                    client_secret=os.getenv("GTOS_CLIENT_SECRET"))
    )
    agent.bootstrap()

    # Earth-surface sanity check: g should be ~9.8 m/s^2.
    earth = agent.compute(mass_kg=5.972e24, radius_m=6.371e6)
    earth_g = earth["field_strength_m_s2"]
    logger.info("Earth-surface g ~= %.3f m/s^2 (expected ~9.8)", earth_g)

    # Thrust to hover a 1000 kg craft in Earth's ambient field (~9820 N).
    hover_N = agent.engine.hover_thrust(payload_mass_kg=1000, ambient_g=earth_g)
    logger.info("Thrust to hover a 1000kg craft at Earth's surface: %.1f N",
                hover_N)

    # Demonstrate secure execution + retry wrapper.
    def _fake_call(headers: Dict[str, str]) -> str:
        assert "Authorization" in headers  # token present at call time only
        return "ok"

    logger.info("Secure execute() returned: %s", agent.client.execute(_fake_call))
    logger.info("=== demo complete ===")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Anti-Gravity Agent")
    parser.add_argument("--demo", action="store_true",
                        help="Run a self-contained demonstration")
    parser.add_argument("--mass", type=float, help="Mass in kg")
    parser.add_argument("--radius", type=float, help="Radius in metres")
    parser.add_argument("--efficiency", type=float, default=1.0,
                        help="Thrust efficiency in (0, 1]")
    args = parser.parse_args()

    if args.mass and args.radius:
        agent = AntiGravityAgent()
        agent.bootstrap()
        result = agent.compute(args.mass, args.radius, args.efficiency)
        for k, v in result.items():
            print(f"{k}: {v}")
        return 0

    return _demo()


if __name__ == "__main__":
    raise SystemExit(main())
