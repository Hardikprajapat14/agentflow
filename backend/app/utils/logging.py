import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_agentflow_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s"))
    root.handlers = [handler]
    root.setLevel(level.upper())
    root._agentflow_configured = True  # type: ignore[attr-defined]
    logging.getLogger("httpx").setLevel(logging.WARNING)
