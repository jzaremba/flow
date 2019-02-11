"""Experimental metadata."""
from builtins import str
import numpy as np

from . import parser


class MissingParentError(Exception):
    """Error thrown if you try to add a bad date/run.

    For adding a date without the mouse or a run without the mouse and date
    already present in metadata.

    """

    pass


class AlreadyPresentError(Exception):
    """Error thrown if a mouse/date/run already exists in metadata."""

    pass


# TODO: This could all be added to the metadata instead.
reversals = {
    'CB173': '160516',
    'AS20': '160827',
    'AS21': '161115',
    'AS23': '161213',
    'OA32': '170406',
    'OA32-H': '181231',
    'OA34': '170602',
    'OA36': '170906',
    'OA37': '171231',
    'OA37-H': '171231',
    'OA38': '171231',
    'AS41': '181231',
    'AS44': '181231',
    'AS46': '181231',
    'AS47-naive': '181231',
    'AS47': '181231',
    'AS51': '181231',
    'OA178': '180702',
    'OA191': '180813',
    'OA192': '180903',
    'OA205': '181001'
}

sleep = {
    'AS21': {
        '161101': {
            5: [-1, -1],
            9: [-1, -1],
            10: [-1, -1],
            11: [-1, -1],
        },
        '161102': {
            5: [-1, -1],
            9: [-1, -1],
            10: [-1, -1],
            11: [-1, -1],
        },
        '161108': {
            5: [-1, -1],
            9: [-1, -1],
            10: [-1, -1],
            11: [-1, -1],
        },
        '161109': {
            5: [-1, -1],
            9: [0, 40],
            10: [0, 40],
            11: [0, 40],
        }
    }
}


def meta(
        mice=None, dates=None, runs=None, run_types=None, tags=None,
        photometry=None, exclude_tags=('bad',), reload_=False):
    """Return metadata as a DataFrame, optionally filtering on any columns.

    All parameters are optional and if passed will be used to filter the
    columns of the resulting DataFrame.

    Parameters
    ----------
    mice : list of str
    dates : list of int
    runs : list of int
    run_types : list of str
    tags : list of str
    photometry : list of str
    exclude_tags : list of str
        List of tags to exclude from result.

    Returns
    -------
    pd.DataFrame
        Index=('mouse', 'date', 'run')
        Columns=('run_type', 'tags', 'photometry')

    """
    df = parser.meta_df(reload_=reload_)

    if mice is not None:
        mouse_slice = list(mice)
    else:
        mouse_slice = slice(None)
    if dates is not None:
        date_slice = list(dates)
    else:
        date_slice = slice(None)
    if runs is not None:
        run_slice = list(runs)
    else:
        run_slice = slice(None)
    df = df.loc(axis=0)[mouse_slice, date_slice, run_slice]

    if run_types is not None:
        df = df[df.run_type.isin(run_types)]

    # Filters that use an apply don't work right on empty DataFrames
    if tags is not None and len(df):
        df = df[df.tags.apply(
            lambda x: all(tag in x for tag in tags))]
    if photometry is not None and len(df):
        df = df[df.photometry.apply(
            lambda x: all(tag in x for tag in photometry))]
    if exclude_tags is not None and len(df):
        df = df[~ df.tags.apply(
            lambda x: any(tag in x for tag in exclude_tags))]

    return df


def add_mouse(mouse, tags=None, overwrite=False, update=False):
    """Add a mouse to the metadata.

    Parameters
    ----------
    mouse : str
    tags : list of str, optional
    overwrite : bool
        If True and Mouse already exists, replace with a new empty Mouse.
    update : bool
        If True and Mouse already exists, append new tags to existing Mouse.

    """
    if overwrite and update:
        raise ValueError('Cannot both update and overwrite a Mouse.')

    # Automatically format tags to list
    if isinstance(tags, str):
        tags = [tags]

    mouse_dict = {'name': mouse,
                  'dates': []}
    metadata = parser.meta_dict()
    existing_mouse = [m for m in metadata['mice'] if m['name'] == mouse]
    assert len(existing_mouse) <= 1
    if len(existing_mouse) == 1:
        if not overwrite and not update:
            raise AlreadyPresentError(
                'Mouse already present in metadata: {}'.format(mouse))
        elif update:
            mouse_dict['dates'] = existing_mouse[0]['dates']
            mouse_dict['tags'] = existing_mouse[0].get('tags', [])
        metadata['mice'].remove(existing_mouse[0])

    if tags is not None:
        if 'tags' not in mouse_dict:
            mouse_dict['tags'] = tags
        else:
            mouse_dict['tags'].extend(tags)

    metadata['mice'].append(mouse_dict)
    parser.save(metadata)
    parser.meta_dict()
    # Clear DataFrame cache
    parser._metadata = None


def add_date(
        mouse, date, tags=None, photometry=None, overwrite=False,
        update=False):
    """Add a date to the metadata.

    Mouse must already exist.

    Parameters
    ----------
    mouse : str
    date : int
    tags : list of str, optional
    photometry : list of str, optional
    overwrite : bool
        If True and Date already exists, replace with a new empty Date.
    update : bool
        If True and Date already exists, append new tags and photometry.

    """
    if overwrite and update:
        raise ValueError('Cannot both update and overwrite a Date.')

    # Automatically format tags to list
    if isinstance(tags, str):
        tags = [tags]

    date_dict = {'date': date,
                 'runs': []}
    metadata = parser.meta_dict()
    existing_mouse = [m for m in metadata['mice'] if m['name'] == mouse]
    if len(existing_mouse) == 0:
        raise MissingParentError('Must first add mouse: {}'.format(mouse))
    assert len(existing_mouse) == 1
    mouse_dict = existing_mouse[0]
    metadata['mice'].remove(mouse_dict)

    existing_date = [d for d in mouse_dict['dates'] if d['date'] == date]
    assert len(existing_date) <= 1
    if len(existing_date) == 1:
        if not overwrite and not update:
            raise AlreadyPresentError(
                'Date already exists in metadata: {}-{}'.format(mouse, date))
        elif update:
            date_dict['runs'] = existing_date[0]['runs']
            date_dict['tags'] = existing_date[0].get('tags', [])
            date_dict['photometry'] = existing_date[0].get('photometry', [])
        mouse_dict['dates'].remove(existing_date[0])

    if tags is not None:
        if 'tags' not in date_dict:
            date_dict['tags'] = tags
        else:
            date_dict['tags'].extend(tags)
    if photometry is not None:
        if 'photometry' not in date_dict:
            date_dict['photometry'] = photometry
        else:
            date_dict['photometry'].extend(photometry)

    mouse_dict['dates'].append(date_dict)
    metadata['mice'].append(mouse_dict)

    parser.save(metadata)
    parser.meta_dict()
    # Clear DataFrame cache
    parser._metadata = None


def add_run(
        mouse, date, run, run_type, tags=None, overwrite=False, update=False):
    """Add a run to the metadata.

    Parameters
    ----------
    mouse : str
    date : int
    run : int
    run_type : str
    tags : list of str, optional
    overwrite : bool
        If True and Run exists, replace with a new empty Run.
    update : bool
        If True and Run exists, append new tags and update run_type.

    """
    if overwrite and update:
        raise ValueError('Cannot both update and overwrite a Run.')

    # Automatically format tags to list
    if isinstance(tags, str):
        tags = [tags]

    run_dict = {'run': run,
                'run_type': run_type}
    metadata = parser.meta_dict()
    existing_mouse = [m for m in metadata['mice'] if m['name'] == mouse]
    if len(existing_mouse) == 0:
        raise MissingParentError('Must first add mouse: {}'.format(mouse))
    assert len(existing_mouse) == 1
    mouse_dict = existing_mouse[0]
    metadata['mice'].remove(mouse_dict)

    existing_date = [d for d in mouse_dict['dates'] if d['date'] == date]
    if len(existing_date) == 0:
        raise MissingParentError('Must first add date: {}-{}'.format(mouse, date))
    assert len(existing_date) == 1
    date_dict = existing_date[0]
    mouse_dict['dates'].remove(date_dict)

    existing_run = [r for r in date_dict['runs'] if r['run'] == run]
    assert len(existing_run) <= 1
    if len(existing_run) == 1:
        if not overwrite and not update:
            raise AlreadyPresentError(
                'Run already exists in metadata: {}-{}-{}'.format(
                    mouse, date, run))
        elif update:
            run_dict['tags'] = existing_run[0].get('tags', [])
        date_dict['runs'].remove(existing_run[0])

    if tags is not None:
        if 'tags' not in run_dict:
            run_dict['tags'] = tags
        else:
            run_dict['tags'].extend(tags)

    date_dict['runs'].append(run_dict)
    mouse_dict['dates'].append(date_dict)
    metadata['mice'].append(mouse_dict)

    parser.save(metadata)
    parser.meta_dict()
    # Clear DataFrame cache
    parser._metadata = None


def reversal(mouse):
    """Return date of the reversal for the mouse or None if not reversed."""
    if mouse not in reversals:
        return None
    return int(reversals[mouse])


def mice(tags=None):
    """Return all mice filtered by a set of tags.

    Parameters
    ----------
    tags : list of str, optional
        If not None, at least 1 run must include all these tags.

    Returns
    -------
    list of str
        Sorted mouse names.

    """
    data = meta(tags=tags)
    return sorted(data.index.get_level_values('mouse').unique())


def dates(mouse, tags=None):
    """Return all dates that a given mouse was imaged.

    Parameters
    ----------
    mouse : str
    tags : list of str, optional
        If not None, dates must include these tags.

    Returns
    -------
    dates : list of int
        Sorted dates the mouse was recorded.

    """
    data = meta(mice=[mouse], tags=tags)
    return sorted(data.index.get_level_values('date').unique())


def runs(mouse, date, run_types=None, tags=None):
    """Return all runs for a given mouse and date.

    Parameters
    ----------
    mouse : str
    date : int
    run_types : list of str, optional
        Optionally filter to specific run types.
    tags : list of str, optional
        Optionally filter by additional tags.

    Returns
    -------
    runs : list of int
        Sorted runs for the given mouse and date.

    """
    data = meta(
        mice=[mouse], dates=[date], run_types=run_types, tags=tags)
    return sorted(data.index.get_level_values('run'))


def data(mouse, date):
    """Return all of the data for a given date as a dict.

    Parameters
    ----------
    mouse : str
    date : int

    Returns
    -------
    dict
        All metadata with following keys:
            mouse : mouse name
            date : date as int
            hungry : list of run indexes for hungry spontaneous runs
            sated : list of run indexes for sated spontaneous runs
            *run_type* : list of run indices for all run types in metadata

    """
    out = {'mouse': mouse, 'date': date}

    date_df = meta(mice=[mouse], dates=[date])

    for run_type, run_type_df in date_df.groupby('run_type'):
        out[str(run_type)] = sorted(run_type_df.index.get_level_values('run'))

    hungry = date_df.loc[(date_df.run_type == 'spontaneous') &
                         date_df.tags.apply(lambda x: 'hungry' in x)]
    out['hungry'] = sorted(hungry.index.get_level_values('run'))
    sated = date_df.loc[(date_df.run_type == 'spontaneous') &
                        date_df.tags.apply(lambda x: 'sated' in x)]
    out['sated'] = sorted(sated.index.get_level_values('run'))

    return out
