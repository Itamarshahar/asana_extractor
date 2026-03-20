"""Entry point for `python -m asana_extractor` and `asana-extractor` CLI."""

from __future__ import annotations

import argparse
import asyncio

from asana_extractor.config import load_config
from asana_extractor.logging import configure_logging, get_logger
from asana_extractor.orchestrator import WorkspaceOrchestrator
from asana_extractor.scheduler import ExtractionScheduler
from asana_extractor.secrets import EnvSecretsProvider
from asana_extractor.state import delete_state
from asana_extractor.tenant import EnvTenantProvider


def main() -> None:
    """Main entry point for `python -m asana_extractor` and `asana-extractor` CLI."""
    # Step 0: Parse CLI args
    parser = argparse.ArgumentParser(description="Asana data extractor")
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single extraction cycle and exit",
    )
    parser.add_argument(
        "--full-extraction",
        action="store_true",
        help="Force a full re-extraction by clearing state files for all workspaces",
    )
    args = parser.parse_args()

    # Step 1: Load and validate config (fail-fast on missing/invalid config.json)
    settings = load_config()

    # Step 2: Configure structured logging
    configure_logging(settings.log_level)
    log = get_logger(__name__)
    log.info(
        "startup",
        extraction_interval=settings.extraction_interval,
        run_once=args.run_once,
        full_extraction=args.full_extraction,
    )

    # Step 3: Load PAT from secrets (fail-fast if ASANA_PAT not set in .env)
    secrets_provider = EnvSecretsProvider()
    pat = secrets_provider.get_secret("ASANA_PAT")  # noqa: F841
    # PAT is validated by loading it; EnvSecretsProvider.get_secret exits on missing key.
    # The TenantProvider below will also need it — for the exercise, EnvTenantProvider
    # reads tenants from config.json which includes PATs per workspace.

    # Step 4: Build orchestrator
    orchestrator = WorkspaceOrchestrator(settings)

    # Step 5: Build tenant provider
    tenant_provider = EnvTenantProvider()

    # Step 5.5: Clear state files if --full-extraction requested
    if args.full_extraction:
        tenants = tenant_provider.list_tenants()
        for tenant in tenants:
            delete_state(settings.output_dir, tenant.workspace_gid)
        log.info("full_extraction_state_cleared", workspace_count=len(tenants))

    # Step 6: Build scheduler
    scheduler = ExtractionScheduler(settings, orchestrator, tenant_provider)

    # Step 7: Run the appropriate mode
    try:
        if args.run_once:
            asyncio.run(scheduler.run_once())
        else:
            asyncio.run(scheduler.run())
    except KeyboardInterrupt:
        # asyncio.run may raise KeyboardInterrupt if signal arrives
        # between event loop iterations. This is a clean exit path.
        pass


if __name__ == "__main__":
    main()
