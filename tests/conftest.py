"""Make the package importable in subprocesses launched by the tests."""
import os
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parents[1])
os.environ["PYTHONPATH"] = ROOT + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
