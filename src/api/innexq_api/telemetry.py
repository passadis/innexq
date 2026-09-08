"""Opt-in Azure telemetry; never export prompts, evidence or customer payloads."""

import logging
import os
from typing import Any


def configure_telemetry(credential: Any) -> None:
    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    from azure.monitor.opentelemetry import configure_azure_monitor

    os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "false"
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    configure_azure_monitor(
        credential=credential,
        logger_name="innexq.audit",
        instrumentation_options={
            name: {"enabled": False}
            for name in (
                "azure_sdk",
                "django",
                "fastapi",
                "flask",
                "psycopg2",
                "requests",
                "urllib",
                "urllib3",
                "httpx",
                "aiohttp_client",
            )
        },
        disable_offline_storage=True,
    )
    logging.getLogger("innexq.audit").setLevel(logging.INFO)
