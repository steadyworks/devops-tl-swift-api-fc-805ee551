# tests/conftest.py
import multiprocessing as mp


def pytest_configure() -> None:
    # Avoid RuntimeError: "context has already been set"
    mp.set_start_method("spawn", force=True)
