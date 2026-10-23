"""Local lecture processing; optional isolated GPU runtime precedes the CPU fallback."""
import sys
from pathlib import Path
from .runtime import configure

configure()

ort_runtime = Path(__file__).resolve().parents[1]/'models/ortgpu12'
if ort_runtime.is_dir() and sys.prefix.endswith('.venv'):
    sys.path.insert(0,str(ort_runtime))
