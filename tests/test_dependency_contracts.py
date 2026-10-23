"""Public core installation requirements and their constraints must agree."""
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT=Path(__file__).resolve().parents[1]


def test_core_requirements_are_compatible_with_locked_constraints():
    locked={canonicalize_name(r.name):r for line in (ROOT/'requirements-lock.txt').read_text('utf-8').splitlines()
            if (text:=line.strip()) and not text.startswith('#') for r in [Requirement(text)]}
    for line in (ROOT/'requirements.txt').read_text('utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        requirement=Requirement(line)
        constraint=locked[canonicalize_name(requirement.name)]
        pins=list(constraint.specifier)
        assert len(pins)==1 and pins[0].operator=='=='
        assert requirement.specifier.contains(pins[0].version),str(requirement)+' conflicts with '+str(constraint)
