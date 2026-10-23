from pathlib import Path
from .common import read_json


def formula_targets(output):
    output=Path(output)
    visuals=read_json(output/'visuals.json',[])
    selection=read_json(output/'formula_selection.json')
    return [v for v in visuals if v['id'] in selection] if selection is not None else [v for v in visuals if v.get('is_representative',True)]
