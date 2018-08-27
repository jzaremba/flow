"""Parser for experiment metadata."""
from copy import deepcopy
import json
import jsonschema
from operator import itemgetter
import os
import pandas as pd

from flow import config

CURRENT_SCHEMA_VERSION = 'v1'

_metadata = None


def validate(metadata=None):
    """Validate the current schema.

    Parameter
    ---------
    metadata : dict, optional
        If None, load the metadata from the config location.

    Raises
    ------
    jsonschema.ValidationError

    """
    global CURRENT_SCHEMA_VERSION
    schema_version = CURRENT_SCHEMA_VERSION
    schema_path = os.path.join(
        os.path.dirname(__file__),
        'metadata.{}.schema.json'.format(schema_version))
    with open(schema_path, 'r') as f:
        schema = json.load(f)

    if metadata is None:
        metadata_path = _get_metadata_path()
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)

    return _validate(metadata, schema)


def meta_dict(reload_=False):
    """Return metadata, load if needed."""
    global _metadata
    if reload_ or _metadata is None:
        metadata_path = _get_metadata_path()
        with open(metadata_path, 'r') as f:
            _metadata = json.load(f)
    return deepcopy(_metadata)


def meta_df():
    """Parse metadata into a pandas dataframe."""
    out = []
    meta = meta_dict()
    for mouse in meta['mice']:
        mouse_name = mouse.get('name')
        mouse_tags = mouse.get('mouse_tags', [])
        for date in mouse['dates']:
            date_num = date.get('date')
            date_tags = date.get('date_tags', [])
            photometry = date.get('photometry', [])
            for run in date.get('runs'):
                run_id = run.get('run')
                run_type = run.get('run_type')
                run_tags = run.get('run_tags', [])
                out.append({
                    'mouse': mouse_name,
                    'mouse_tags': mouse_tags,
                    'date': date_num,
                    'date_tags': date_tags,
                    'photometry': photometry,
                    'run': run_id,
                    'run_tags': run_tags,
                    'run_type': run_type
                })
    return pd.DataFrame(out)


def save(metadata):
    """Save metadata to file.

    First validates format.

    Parameters
    ----------
    metadata : dict
        Dict to be written as JSON.

    """
    validate(metadata)

    # Sort lists sanely
    metadata['mice'] = sorted(metadata['mice'], key=itemgetter('name'))
    for mouse in metadata['mice']:
        mouse['dates'] = sorted(mouse['dates'], key=itemgetter('date'))
        for date in mouse['dates']:
            date['runs'] = sorted(date['runs'], key=itemgetter('run'))

    metadata_path = _get_metadata_path()
    with open(metadata_path, 'w') as f:
        json.dump(
            metadata, f, sort_keys=True, indent=2, separators=(',', ': '))


def _get_metadata_path():
    """Find the metadata path, raise error if not configured."""
    params = config.params()
    try:
        metadata_path = params['paths']['metadata']
    except KeyError:
        raise ValueError(
            'Metadata path is not configured. ' +
            'Run flow.config.reconfigure() to update package configuration.')

    return metadata_path


def _validate(metadata, schema):
    jsonschema.validate(metadata, schema)
    return True
