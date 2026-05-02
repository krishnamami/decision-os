from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional, Union

from fastapi import FastAPI

from .deps import Platform, build_default_platform
from .routes import router


# ─────────────────────────────────────────────────────────────────────
# create_app — single entry point for FastAPI servers, tests, and the
# scheduled real-backend verification.
#
# Tests construct their own Platform (custom TraceWriter, alternative
# resolver, registered personas) and pass it in. uvicorn / docker boot
# uses build_default_platform() with the in-memory backends and the
# `seed_demo_data=True` flag flips on auto-replay of all 4 seed
# scenarios so the UI has data to show before any human types a curl.
#
# Production swap (Postgres + Redis) replaces build_default_platform
# only; everything else here works unchanged.
# ─────────────────────────────────────────────────────────────────────


DEFAULT_DEMO_SCENARIOS: tuple[str, ...] = (
    "happy_path",
    "fraud_block",
    "contamination",
    "compliance_block",
)


async def _bootstrap_demo(platform: Platform) -> None:
    """Register all 12 lending personas and replay the 4 seed scenarios
    so the UI has applications + traces + queued decisions on first
    page load. Cheap (~50ms total) and deterministic."""

    # Local imports keep the api package independent of the lending
    # domain pack — tests that don't want lending data can pass
    # seed_demo_data=False and skip this entirely.
    from domains.lending.personas import register_with_platform
    from domains.lending.seed_events.runner import run_scenario

    register_with_platform(platform)
    for scenario in DEFAULT_DEMO_SCENARIOS:
        try:
            await run_scenario(platform, scenario)
        except Exception as err:  # pragma: no cover — visible in dev only
            # Swallow scenario failures so a bad fixture doesn't kill
            # the whole UI boot. Surfaces as an empty application list
            # rather than a 500 — easier to debug.
            print(f"[bootstrap] scenario {scenario!r} failed: {err}")


def create_app(
    platform: Optional[Platform] = None,
    *,
    decisions_path: Union[str, Path] = "domains/lending/decisions.yaml",
    seed_demo_data: bool = False,
    mount_ui: bool = True,
) -> FastAPI:
    if platform is None:
        platform = build_default_platform(decisions_path=decisions_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if seed_demo_data:
            await _bootstrap_demo(platform)
        yield
        # No teardown needed — in-memory backends die with the process.

    app = FastAPI(
        title="Decision OS",
        version=platform.spec.version,
        description=(
            "Structured, governed, AI-augmented decisioning. "
            "POST /events to ingest, POST /override to capture a human "
            "override, GET /decisions/{app}/{decision} to read a "
            "decision record, GET /trace/{id} to read a trace. "
            "UI mounted at /."
        ),
        lifespan=lifespan,
    )
    app.state.platform = platform
    app.include_router(router)

    if mount_ui:
        # Local import — ui/ depends on the api package, so we resolve
        # the import lazily to keep this module loadable even if the
        # ui package hasn't been installed.
        from ui import router as ui_router
        app.include_router(ui_router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "domain": platform.spec.domain,
            "version": platform.spec.version,
            "agents": str(len(platform.agents)),
            "connectors": str(len(platform.connectors)),
            "applications": str(len(_known_application_ids(platform))),
        }

    return app


def _known_application_ids(platform: Platform) -> set[str]:
    """Cheap distinct-app-id walk over the in-memory durable store.

    Powers /health and the application list view. For the Postgres
    swap this becomes a SELECT DISTINCT entity_id WHERE entity_type
    = 'Application' AND decision_id IS NULL."""
    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None)
    if not isinstance(records, list):
        return set()
    return {
        r.entity_id for r in records
        if r.entity_type == "Application"
        and r.decision_id is None
        and r.superseded_at is None
    }


app: Optional[FastAPI] = None


def get_app() -> FastAPI:
    """Lazy module-level singleton for `uvicorn api.main:get_app --factory`.

    Auto-seeds demo data so a fresh server always has applications to
    render. Tests bypass this by calling create_app() directly with
    seed_demo_data=False."""
    global app
    if app is None:
        app = create_app(seed_demo_data=True)
    return app


__all__ = ["create_app", "get_app", "_known_application_ids"]
