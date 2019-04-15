"""Train the reactivation classifier."""
try:
    from bottleneck import nanmean
except ImportError:
    from numpy import nanmean
import numpy as np

from . import aode
from .. import config


def train_classifier(
        run, training_runs=None, running_runs=None, training_date=None,
        verbose=True, **pars):
    """
    Function to prepare all data to train the classifier.

    Parameters
    ----------
    run : Run
        Run that the classifier will be applied to.
    training_runs : RunSorter, optional
        If specified, use these runs to train the classifier. If not passed,
        defaults to all runs from the date of run_type == 'training'.
    running_runs : RunSorter, optional
        If specified, use these runs to train running period for the
        classifier. If not passed, defaults to all runs from the date of
        run_type == 'running'.
    training_date : Date, optional
        Optionally train on an alternate date.
    verbose : bool
        If True, print out info about the trained model.
    **pars
        All other classifier parameters are collect as keyword arguments. These
        will override the default arguments in ..config.default(). Parameter
        names with '-' should be entered with a '_' and will be converted.

    Returns
    -------
    model : aode.AODE
        Trained model.
    params : dict
        Parameters.
    nan_cells
        Cell mask of cells with NaNs in training data.

    """
    # Allow for training on a different date than the date that we want to
    # classify.
    if training_date is None:
        training_date = run.parent
    else:
        # This hasn't really been tested. First person to use it, feel free to
        # change the input to whatever is useful (Date object, relative day
        # shift, absolute date int, etc.).
        if training_date != run.parent:
            raise NotImplementedError

    # Infer training and running runs if they are not specified
    if training_runs is None:
        training_runs = training_date.runs(
            run_types=['training'], tags=['hungry'])
    else:
        assert all(run.parent == training_date for run in training_runs)
    if running_runs is None:
        running_runs = training_date.runs(
            run_types=['running'], tags=['hungry'])
    else:
        assert all(run.parent == training_date for run in running_runs)

    # Get default parameters and update with any new ones passed in.
    params = config.default()
    for key, val in pars.items():
        # Convert to match old parameters
        params[key.replace('_', '-')] = val

    # Convert parameters specified in seconds into frames.
    params = _convert_time_to_frames(
        params, training_date.framerate)

    # Collect all classifier states
    all_cses = {key: key for key in params['probability']
                if 'disengaged' not in key}
    all_cses.update(params['training-equivalent'])

    # Pull all training data
    traces = _get_traces(
        run, training_runs, running_runs, all_cses,
        trace_type=params['trace-type'],
        length_fr=params['stimulus-frames'],
        pad_fr=params['excluded-time-around-onsets-frames'],
        offset_fr=params['stimulus-offset-frames'],
        running_threshold_cms=params['other-running-speed-threshold-cms'],
        lick_cutoff=params['lick-cutoff'],
        lick_window=params['lick-window'],
        correct_trials=params['train-only-on-positives'],
        running_fraction=params['other-running-fraction'],
        max_n_onsets=params['maximum-cs-onsets'],
        remove_stim=params['remove-stim'])

    # Remove any binarization
    for cs in traces:
        traces[cs] *= params['analog-training-multiplier']
        traces[cs] = np.clip(traces[cs], 0, 1)

    model = aode.AODE()
    model.train(traces, params['classifier'])
    if verbose:
        print(model.describe())

    params.update({'comparison-date': run.date,
                   'comparison-run': run.run,
                   'mouse': run.mouse,
                   'training-date': training_date.date,
                   'training-other-running-runs':
                       sorted(r.run for r in running_runs),
                   'training-runs':
                       sorted(r.run for r in training_runs)})

    return model, params, _nan_cells(traces)


def classify_reactivations(
        run, model, params, nan_cells=None, merge_cses=None,
        replace_data=None, replace_priors=None, replace_temporal_prior=None,
        replace_integrate_frames=None):
    """Given a run and trained model, classify reactivations.

    Parameters
    ----------
    run : Run
        Run that the classifier will be applied to.
    model : aode.AODE
        A fully-trained model.
    params : dict
        Parameters for classifier.
    nan_cells : np.ndarray of bool
        Cell mask of cells to exclude from temporal prior. Activity outliers
        are also automatically removed.
    merge_cses : optional, list
        List of class names. Merges the results of later values into the first
        one.
    replace_data : matrix (ncells, ntimes)
        Replacement data if not None
    replace_priors : dict of floats
        The prior probabilities for each category to replace that in parameters
    replace_temporal_prior : vector
        A replacement temporal prior to generate the frame priors
    replace_integrate_frames : int
        Can change the frame integration number without changing the parameters.
        This is useful if the data are already passed through a rolling max filter.

    Returns
    -------
    dict
        Results dict.

    """
    if merge_cses is None:
        merge_cses = []

    if replace_data is not None:
        full_traces = replace_data
    else:
        full_traces = run.trace2p().trace(params['trace-type'])
    if nan_cells is None:
        nan_cells = np.any(np.invert(np.isfinite(full_traces)), axis=1)

    if replace_priors is not None:
        priors = replace_priors
    else:
        priors = {cs: params['probability'][cs] for cs in model.classnames}

    if params['remove-stim'] and replace_data is None:
        t2p = run.trace2p()
        pad_s = params['classification-ms'] / 1000. / 2.
        post_pad_s = 0.0 + pad_s
        post_pav_pad_s = 0.5 + pad_s
        # Round-up all times to a full frame
        pad_s = np.ceil(pad_s*t2p.framerate)/t2p.framerate
        post_pad_s = np.ceil(post_pad_s*t2p.framerate)/t2p.framerate
        post_pav_pad_s = np.ceil(post_pav_pad_s*t2p.framerate)/t2p.framerate
        all_stim_mask = t2p.trialmask(
            cs='', errortrials=-1, fulltrial=False, padpre=pad_s,
            padpost=post_pad_s)
        pav_mask = t2p.trialmask(
            cs='pavlovian*', errortrials=-1, fulltrial=False,
            padpre=pad_s, padpost=post_pav_pad_s)
        blank_mask = t2p.trialmask(
            cs='blank*', errortrials=-1, fulltrial=False,
            padpre=pad_s, padpost=post_pav_pad_s)
        stim_mask = (all_stim_mask | pav_mask) & ~blank_mask
    else:
        stim_mask = None

    if params['temporal-dependent-priors'] and replace_temporal_prior is None:
        baseline, variance, outliers = _activity(
            run,
            baseline_activity=params['temporal-prior-baseline-activity'],
            baseline_sigma=params['temporal-prior-baseline-sigma'],
            trace_type=params['trace-type'])
        # Make sure cells with any NaN's and outliers are removed from the
        # temporal prior
        outliers = np.bitwise_or(outliers, nan_cells)

        tpriorvec = aode.temporal_prior(
            full_traces[np.invert(outliers), :], actmn=baseline,
            actvar=variance, fwhm=params['temporal-prior-fwhm-frames'],
            stim_mask=stim_mask)
        used_priors = aode.assign_temporal_priors(
            priors, tpriorvec, 'other')
    elif params['temporal-dependent-priors']:
        used_priors = aode.assign_temporal_priors(
            priors, replace_temporal_prior, 'other')
    else:
        # NOTE: this hasn't really been tested
        # Default to equal probability
        tpriorvec = np.ones(full_traces.shape[1])
        if stim_mask is not None:
            tpriorvec[stim_mask] = 0
        used_priors = aode.assign_temporal_priors(
            priors, tpriorvec, 'other')

    full_traces = np.clip(
        full_traces*params['analog-comparison-multiplier'], 0.0, 1.0)

    integrate_frames = params['classification-frames'] \
        if replace_integrate_frames is None \
        else replace_integrate_frames
    results, data, likelihoods = model.compare(
        full_traces, integrate_frames, used_priors)

    # Optionally merge together multiple trained classes into one
    if len(merge_cses) > 0:
        merge1 = merge_cses[0]
        for merge2 in merge_cses[1:]:
            results[merge1] += results[merge2]
            results.pop(merge2)

    out = {'parameters': params,
           'results': results,
           'likelihood': likelihoods,
           'marginal': model.marginal,
           'priors': used_priors,
           'cell_mask': np.invert(nan_cells)}

    return out


def _activity(
        run, baseline_activity=0., baseline_sigma=3.0,
        trace_type='deconvolved'):
    """
    Get the activity levels for the temporal classifier.

    Parameters
    ----------
    run : Run
    baseline_activity : float
        Scale factor of baseline activity.
        'temporal-prior-baseline-activity' in classifier parameters.
    baseline_sigma : float
        Scale factor of baseline variance.
        'temporal-prior-baseline-sigma' in classifier parameters.
    trace_type : {'deconvolved'}
        This only works on deconvolved data for now.

    Returns
    -------
    baseline activity, variance of activity, outliers

    """
    if trace_type != 'deconvolved':
        raise ValueError(
            'Temporal classifier only implemented for deconvolved data.')

    if run.run_type == 'spontaneous' and 'sated' in run.tags:
        runs = run.parent.runs(run_types=['spontaneous'], tags=['sated'])
        spontaneous = True
    elif run.run_type == 'spontaneous' and 'hungry' in run.tags:
        runs = run.parent.runs(run_types=['spontaneous'], tags=['hungry'])
        spontaneous = True
    elif run.run_type == 'training':
        runs = run.parent.runs(run_types=['training'])
        spontaneous = False
    else:
        raise ValueError(
            'Unknown run_type and tags, not sure how to calculate activity.')

    baseline, variance, outliers = None, None, None
    if spontaneous:
        popact, outliers = [], []
        for r in runs:
            t2p = r.trace2p()
            pact = t2p.trace('deconvolved')
            fmin = t2p.lastonset()
            mask = t2p.inactivity()
            mask[:fmin] = False

            if len(popact):
                popact = np.concatenate([popact, pact[:, mask]], axis=1)
            else:
                popact = pact[:, mask]

            trs = t2p.trace('deconvolved')[:, fmin:]
            cellact = np.nanmean(trs, axis=1)
            outs = cellact > np.nanmedian(cellact) + 2*np.std(cellact)

            if len(outliers) == 0:
                outliers = outs
            else:
                outliers = np.bitwise_or(outliers, outs)

        if len(popact):
            popact = np.nanmean(popact[np.invert(outliers), :], axis=0)

            baseline = np.median(popact)
            variance = np.std(popact)
            outliers = outliers
    else:
        popact = []
        for r in runs:
            t2p = r.trace2p()
            ncells = t2p.ncells
            pact = np.nanmean(t2p.trace('deconvolved'), axis=0)
            skipframes = int(t2p.framerate*4)

            for cs in ['plus*', 'neutral*', 'minus*', 'pavlovian*']:
                onsets = t2p.csonsets(cs)
                for ons in onsets:
                    pact[ons:ons+skipframes] = np.nan
            popact = np.concatenate([popact, pact[np.isfinite(pact)]])

        if len(popact):
            # baseline = np.median(popact)

            # Exclude extremes
            percent = 2.0
            popact = np.sort(popact)
            trim = int(percent*popact.size/100.)
            popact = popact[trim:-trim]

            baseline = np.median(popact)  # Moved to after extreme exclusion on 032619
            variance = np.std(popact)
            outliers = np.zeros(ncells, dtype=bool)

    if baseline is None:
        baseline, variance = 0.01, 0.08*baseline_sigma
    else:
        baseline *= baseline_activity
        variance *= baseline_sigma

    return baseline, variance, outliers


def _get_traces(
        run, runs, running_runs, all_cses, trace_type='deconvolved', length_fr=15,
        pad_fr=31, offset_fr=1, running_threshold_cms=4., correct_trials=False,
        lick_cutoff=-1, lick_window=(-1, 0), running_fraction=0.3,
        max_n_onsets=-1, remove_stim=True):
    """
    Return all trace data by stimulus chopped into same sized intervals.

    Parameters
    ----------
    run : Run
        The target run that we are training for.
    runs : RunSorter
        Runs to use for training of stimulus presentations.
    running_runs : RunSorter
        Running-only runs used to train running times.
    all_cses : dict
        Re-map cs names in order to combine some cses.
    length_fr : int
        Chop up the training data into chunks of this many frames.
    pad_fr : int or (int, int)
        Number of frames to pad around the stimulus onset.
    offset_fr : int
        Number of frames to pad around the stimulus offset.
    running_threshold_cms : float
        Minimum threshold above which the mouse is considered to be running.
    correct_trials : bool
        Limit training to only correct trials.
    lick_cutoff : int, optional
        Toss trials with more than lick_cutoff licks.
    lick_window : tuple, optional
        Count licks within this window to choose which to toss out.
    running_fraction : float
        Intervals must have greater than this fraction of frames to be
        considered running.
    max_n_onsets : int, optional
        If >0, limit the number of allowed onsets to this number, to match
        the amount of training data across states.
    remove_stim : boolean
        If True, stimulus frames will be removed before classification, so we
        can use them for training.

    Returns
    -------
    dict of np.ndarray
        Keys are cs name, value is nonsets x ncells x nframes

    """
    if run not in running_runs:
        # Prepare running baseline data.
        # NOTE: running thresholding is done differently here than later during
        # stimulus runs.
        out = {'other-running': _get_run_onsets(
            runs=running_runs,
            length_fr=length_fr,
            pad_fr=pad_fr,
            offset_fr=offset_fr,
            running_threshold_cms=running_threshold_cms)}

    for training_run in runs:
        t2p = training_run.trace2p()

        # Get the trace from which to extract time points
        trs = t2p.trace(trace_type)

        # If the target run is also a training run, make sure that we aren't
        # training on the same data that will later be used for comparison
        if remove_stim or training_run != run:
            # Search through all stimulus onsets, correctly coding them
            for ncs in t2p.cses():  # t.cses(self._pars['add-ensure-quinine']):
                if ncs in all_cses:
                    # Remap cs name if needed
                    # NOTE: blank trials are just labeled 'other' and not checked
                    # for running.
                    cs = all_cses[ncs]
                    # Initialize output
                    if cs not in out:
                        out[cs] = []

                    ons = t2p.csonsets(
                        ncs, 0 if correct_trials else -1, lick_cutoff, lick_window)

                    for on in ons:
                        start = on + offset_fr
                        toappend = trs[:, start:start + length_fr]
                        # Make sure interval didn't run off the end.
                        if toappend.shape[1] == length_fr:
                            out[cs].append(toappend)

        # If the target run is in the training runs, don't use the times
        # that will later be used for comparison.
        if training_run != run:
            # Add all onsets of "other" frames
            others = t2p.nocs(length_fr, pad_fr, -1)

            if len(t2p.speed()) > 0:
                running = t2p.speed() > running_threshold_cms
                for ot in others:
                    start = ot + offset_fr
                    if nanmean(running[start:start + length_fr]) > \
                            running_fraction:
                        out['other-running'].append(
                            trs[:, start:start + length_fr])
                    else:
                        out['other'].append(
                            trs[:, start:start + length_fr])

    # Selectively remove onsets if necessary
    if max_n_onsets > 0:
        for cs in out:
            if 'other' not in cs:
                print('WARNING: Have not yet checked new timing version')

                # Account for shape of array
                if len(out[cs]) > max_n_onsets:
                    out[cs] = np.random.choice(
                        out[cs], max_n_onsets, replace=False)

    for cs in out:
        out[cs] = np.array(out[cs])

    return out


def _get_run_onsets(
        runs, length_fr, pad_fr, running_threshold_cms, offset_fr):
    """
    Return times of running without stimulus.

    Parameters
    ----------
    runs : RunSorter
        Runs in which to search for running time.
    length_fr : int
        Desired length of each running interval.
    pad_fr : int
        Number of frames to pad around the stimulus.
    offset_ft : int
        Number of frames to shift running intervals.

    Returns
    -------
    list of np.ndarray
        nonsets x (ncells x nframes)

    """
    out = []
    for run in runs:
        t2p = run.trace2p()
        tr = t2p.trace('deconvolved')

        # Add all onsets of "other" frames
        others = t2p.nocs(length_fr, pad_fr,
                          running_threshold_cms)
        for ot in others:
            start = ot + offset_fr
            out.append(tr[:, start:start + length_fr])

    return out


def _convert_time_to_frames(pars, framerate):
    """Convert milliseconds to numbers of frames based on the framerate."""
    pars['stimulus-frames'] = \
        int(round(pars['stimulus-training-ms']/1000.0*framerate))
    pars['stimulus-offset-frames'] = \
        int(round(pars['stimulus-training-offset-ms']/1000.0*framerate))
    pars['classification-frames'] = \
        int(round(pars['classification-ms']/1000.0*framerate))

    # Make the exclusion time a tuple rather than an int
    if isinstance(pars['excluded-time-around-onsets-ms'], int):
        pars['excluded-time-around-onsets-ms'] = (
            pars['excluded-time-around-onsets-ms'],
            pars['excluded-time-around-onsets-ms'])

    # Then convert to frames
    pars['excluded-time-around-onsets-frames'] = (
        int(round(pars['excluded-time-around-onsets-ms'][0]/1000.0*framerate)),
        int(round(pars['excluded-time-around-onsets-ms'][1]/1000.0*framerate)))

    pars['temporal-prior-fwhm-frames'] = \
        int(round(pars['temporal-prior-fwhm-ms']/1000.0*framerate))

    return pars


def _nan_cells(traces):
    """
    Return mask of cells with any NaN values for any stimulus.

    Parameters
    ----------
    traces : dict of np.ndarray
        Keys are stimulus names, values are nonsets x ncells x nframes arrays.

    Returns
    -------
    np.ndarray
        ncells length mask, True for cells that have any NaN's in their traces.

    """
    # Find all cells with NaNs
    nancells = []
    ncells = -1
    for cs in traces:
        if len(traces[cs]) > 0:
            ncells = np.shape(traces[cs])[1]
            ns = np.sum(np.sum(np.invert(np.isfinite(
                traces[cs])), axis=2), axis=0)
            vals = np.arange(ncells)
            nancells.extend(vals[ns > 0])

    # Set _mask_cells if it hasn't been set
    out = np.zeros(ncells, dtype=bool)

    # Convert nancells to a list of good cells
    nancells = np.array(list(set(nancells)))
    if len(nancells) > 0:
        print('Warning: %i cells have NaNs'%len(nancells))
        out[nancells] = True

    return out
