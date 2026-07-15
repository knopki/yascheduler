# switch-to-standard-logging

Replace the YaLogger/get_logger/.trace() abstraction with idiomatic stdlib logging: module-local logging.getLogger(__name__), structured trace via logger.debug(msg, extra={...}), and a LogFormatter that discriminates trace from regular by DEBUG level plus extra attributes diffed against native LogRecord keys.
