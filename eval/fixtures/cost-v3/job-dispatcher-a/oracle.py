"""Run the sealed dispatcher regression probes without exposing truth to review."""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('dispatcher_oracle_support',
                                            Path(__file__).resolve().parent.parent / 'dispatcher_oracle.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
run_checks = support.run_checks
apply_repair = support.apply_repair

if __name__ == '__main__':
    sys.exit(support.main())
