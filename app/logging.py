import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def log_event(event: str, **fields):
    logger.info(
        json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True)
    )
