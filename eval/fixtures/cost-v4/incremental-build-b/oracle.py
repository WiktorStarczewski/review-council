"""Run private build observations outside the reviewed source roots."""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('private_build_oracle', ROOT.parent / 'build_oracle.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
apply_repair = support.apply_repair

def run_checks(before_root=None, after_root=None):
    return support.run_checks(before_root, after_root, ROOT, clean=True)

if __name__ == '__main__':
    sys.exit(support.main(ROOT, clean=True))
