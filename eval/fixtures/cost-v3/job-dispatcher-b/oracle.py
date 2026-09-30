"""Prove the clean dispatcher change and its observable contract controls."""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('dispatcher_clean_oracle_support', ROOT.parent / 'dispatcher_oracle.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)

def run_checks(before_root=None, after_root=None):
    return support.run_checks(before_root, after_root, case_root=ROOT, clean=True)

if __name__ == '__main__':
    sys.exit(support.main(case_root=ROOT, clean=True))
