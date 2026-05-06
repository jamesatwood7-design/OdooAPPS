import json
import logging
import os
import datetime as _dt


class JsonlHandler(logging.Handler):
    """Writes records that have a `.payload` dict attribute as JSON lines."""

    def __init__(self, path):
        super().__init__()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._fh = open(path, 'a', encoding='utf-8')

    def emit(self, record):
        payload = getattr(record, 'payload', None)
        if payload is None:
            return
        try:
            self._fh.write(json.dumps(payload, default=str) + '\n')
            self._fh.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        try:
            self._fh.close()
        finally:
            super().close()


def setup_logging(log_dir, verbose=False):
    """Configure stdout (human-readable) + JSONL (machine-readable) logging."""
    os.makedirs(log_dir, exist_ok=True)
    today = _dt.date.today().isoformat()
    jsonl_path = os.path.join(log_dir, f'migration-{today}.jsonl')

    logger = logging.getLogger('migration')
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    stream = logging.StreamHandler()
    stream.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(stream)

    jsonl = JsonlHandler(jsonl_path)
    jsonl.setLevel(logging.INFO)
    logger.addHandler(jsonl)

    return logger


def log_record(logger, level, message, **payload):
    """Log a human message and structured payload in one call."""
    record = logger.makeRecord(
        logger.name, level, fn='', lno=0, msg=message, args=(), exc_info=None,
    )
    record.payload = payload
    logger.handle(record)
