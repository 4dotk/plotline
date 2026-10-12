import logging

# Library logging: silent unless the application configures it (log.configure_logging,
# tests/conftest.py). Stops Python's last-resort handler printing warnings to stderr.
logging.getLogger("plotline").addHandler(logging.NullHandler())


def main() -> None:
    print("Hello from plotline!")
