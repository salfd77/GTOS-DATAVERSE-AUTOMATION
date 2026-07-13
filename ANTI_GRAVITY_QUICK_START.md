# 🚀 Anti-Gravity Agent — Quick Start (Developer Guide)

**Companion to:** `ANTI_GRAVITY_STRATEGIC_PLAN.md` and `ANTI_GRAVITY_PROJECT_SUMMARY.md`
**Applies to:** `anti_gravity_agent.py` (Phase 1 — Foundation reference template)
**Status:** Reference template. This is a runnable scaffold, **not** a finished
production service. See "What this is / is not" below.

---

## 1. What this is / what it is *not*

| ✅ This template **is** | ❌ This template is **not** |
|---|---|
| A single-file, std-lib-only Python scaffold you can run today | A deployed production service |
| A faithful port of the **proven GTOS patterns** (token masking, smart back-off, typed exceptions, env config) | The full 6-module project drawn in the strategic plan |
| A base to grow the real engine, API layer, and GTOS bridge on | A guarantee of the aspirational metrics (85% coverage, 99.9% uptime, etc.) — those are *targets*, not current state |

The strategic plan describes the **destination**. This file + `anti_gravity_agent.py`
are the **first concrete step** toward it.

---

## 2. Prerequisites

- Python **3.10+**
- No third-party packages required for the template itself
  (`python-dotenv`, `requests`, `msal` become relevant once you wire real auth/HTTP).

```bash
python --version   # expect 3.10 or newer
```

---

## 3. Run it in 30 seconds

```bash
# Self-contained demo (Earth-gravity sanity check + secure-call demo)
python anti_gravity_agent.py --demo

# One-off computation from the CLI
python anti_gravity_agent.py --mass 1000 --radius 6.371e6 --efficiency 0.9
```

Expected demo highlights:
- Earth-surface field strength prints **≈ 9.8 m/s²** (validates the core maths).
- The secure `execute()` path confirms the token is present **only** at call time.

---

## 4. The 6 inherited GTOS patterns (and where they live)

| # | Pattern | Where in `anti_gravity_agent.py` |
|---|---------|----------------------------------|
| 1 | 🔒 **Token protection** — never stored in session/headers, injected at execution time | `AntiGravityClient._headers()`, `Credentials` (secret/token `repr=False`) |
| 2 | 🧾 **Secret masking in logs** | `SecretMaskingFilter` + `build_logger()` |
| 3 | ⚡ **Smart exponential back-off** (10s → 60s cap, max 8 retries) | `SmartRetryManager` |
| 4 | 🛡️ **Typed exception hierarchy** (5 specific + base + exhausted-retries) | `AntiGravityError` and subclasses |
| 5 | ⚙️ **Env-based configuration** — nothing hard-coded | `Config` |
| 6 | 🧪 **Deterministic, testable core** — no I/O in the engine | `GravityEngine` |

---

## 5. Configuration (environment variables)

All optional; sane defaults ship in `Config`.

```bash
# Computation
export AG_COMPUTATION_TIMEOUT=300
export AG_BATCH_SIZE=1000

# Retry / back-off
export AG_MAX_RETRIES=8
export AG_INITIAL_DELAY=10
export AG_MAX_DELAY=60

# HTTP / integration
export AG_REQUEST_TIMEOUT=30
export AG_API_VERSION=v1
export GTOS_DATAVERSE_URL=https://YOUR_ORG.crm.dynamics.com

# Auth (only if you use client credentials instead of interactive/device-code)
export GTOS_CLIENT_ID=...
export GTOS_CLIENT_SECRET=...

# Logging
export AG_LOG_LEVEL=INFO
```

> Never commit real secrets. Copy patterns from the repo's `.env.example`.

---

## 6. Use it as a library

```python
from anti_gravity_agent import AntiGravityAgent, Credentials, ComputationValidationError

agent = AntiGravityAgent(Credentials(client_id="...", client_secret="..."))
agent.bootstrap()

result = agent.compute(mass_kg=1000, radius_m=6.371e6, efficiency=0.9)
print(result["anti_gravity_thrust_N"])

try:
    agent.compute(mass_kg=-5, radius_m=6.371e6)      # invalid input
except ComputationValidationError as e:
    print("Caught precisely:", e)
```

Secure, retry-protected outbound call:

```python
def call_api(headers):        # headers already contain a fresh, masked token
    # requests.get(url, headers=headers, timeout=Config.REQUEST_TIMEOUT)
    return "ok"

agent.client.execute(call_api)   # runs under SmartRetryManager
```

---

## 7. Minimal test (copy into `test_anti_gravity_agent.py`)

```python
import math
import pytest
from anti_gravity_agent import (
    GravityEngine, AntiGravityClient, Credentials, SmartRetryManager,
    ComputationValidationError, ComputationLockedError, ExhaustedRetriesError,
)


def test_earth_gravity_is_about_9_8():
    g = GravityEngine().field_strength(5.972e24, 6.371e6)
    assert math.isclose(g, 9.8, rel_tol=0.02)


def test_negative_mass_rejected():
    with pytest.raises(ComputationValidationError):
        GravityEngine().field_strength(-1, 6.371e6)


def test_token_only_present_at_call_time():
    c = AntiGravityClient(Credentials(token="secret-tok"))
    captured = {}
    c.execute(lambda h: captured.update(h))
    assert captured["Authorization"] == "Bearer secret-tok"


def test_retry_gives_up_without_sleeping_forever():
    calls = {"n": 0}
    def always_locked():
        calls["n"] += 1
        raise ComputationLockedError("locked")
    mgr = SmartRetryManager(max_retries=3, sleep_fn=lambda _s: None)  # no real sleep
    with pytest.raises(ExhaustedRetriesError):
        mgr.execute_with_retry(always_locked)
    assert calls["n"] == 3
```

Run:

```bash
pip install pytest
pytest -q
```

---

## 8. Next steps toward the full plan

Phase 1 (this template) → then, per `ANTI_GRAVITY_STRATEGIC_PLAN.md`:

1. **Split** the single file into the 6 modules (core / security / integration /
   data / testing / docs).
2. **Wire real auth** (MSAL device-code or client-credentials) into
   `AntiGravityClient.authenticate()`.
3. **Build the GTOS bridge** (`gtos_bridge.py`) using the read/write patterns
   already validated in `provision_gtos_dataverse.py`.
4. **Add the API layer** (FastAPI) and real persistence/cache.
5. **Grow the test suite** toward the 100+ / 85%-coverage target.
6. **Containerize** (Docker) and add CI.

---

**Document:** Anti-Gravity Agent Quick Start
**Author:** Anti-Gravity Engineering (bootstrapped from GTOS patterns)
