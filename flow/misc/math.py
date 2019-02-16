from __future__ import division, print_function
from builtins import range

import numpy as np
import pandas as pd
import patsy
import re
from rpy2.robjects import pandas2ri
from rpy2.robjects.packages import importr
from scipy.stats import pearsonr
import statsmodels.api as sm


def subformula(formula, data):
    """
    Subset a dataframe to only include the essential elements for a formula.

    :param formula: formula pattern
    :return: subset of data frame
    """

    formula = re.sub('[\~|\+|\*|\(|\)|\|]', ' ', formula)
    keys = formula.split(' ')
    keys = list(set([k for k in keys if len(k) > 0 and not re.match('(\d|factor)', k)]))
    return data.loc[:, keys].copy()


def _mixed_keys(y, x, random_effects, categorical, continuous_random_effects):
    """
    Return the key names for x, y, and random_effects
    Parameters
    ----------
    y
    x
    random_effects

    Returns
    -------
    list of strs
        Keys to be extracted from dataframe

    """

    out = [y] + [v for v in x] + [v for v in categorical]
    res = [v for v in random_effects] + [v for v in continuous_random_effects]
    out += [vv for v in res for vv in v.split(':') if len(vv) > 0]
    return out


def mixed_effects_model(df, y, x=(), random_effects=(), categorical=(),
                        continuous_random_effects=(), family='gaussian',
                        dropzeros=False, nonlinear=False, R=False):
    """
    Create and run a mixed-effects general(ized) linear model.

    Parameters
    ----------
    df : Pandas DataFrame
    y : str
        The value in a dataframe to be fit
    x : tuple of str
        A tuple of fixed effects to fit
    random_effects : tuple of str
        A tuple of random effects to fit
    family : str {'gaussian', 'gamma'}
    link : str {'identity', 'log'}
    dropzeros : bool
        If true, remove all cases in which y is 0.
    nonlinear : bool
        If true, run a generalized linear model
        rather than a general linear model.
    R : bool
        Force the use of the R package

    Returns
    -------
    model

    """

    # Sanitize inputs
    if isinstance(x, basestring):
        x = (x, )
    if isinstance(categorical, basestring):
        categorical = (categorical, )
    if isinstance(random_effects, basestring):
        random_effects = (random_effects, )

    # Curate the data to a minimal size
    df_keys = _mixed_keys(y, x, random_effects, categorical, continuous_random_effects)
    sub = df.loc[:, df_keys].copy()
    if dropzeros:
        sub.replace(0, np.nan, inplace=True)
    sub.dropna(inplace=True)

    # Convert columns of strings to integer factors
    for reff in random_effects:
        reff = reff.split(':')
        for v in reff:
            if len(v) > 0:
                sub[v], _ = pd.factorize(sub[v])

    # Convert categorical variables to strings
    alpha = 'abcdefghijklmnopqrstuvwxyz'
    for c in categorical:
        vals = sub[c].unique()
        sub[c] = sub[c].replace({v:alpha[i] for i, v in enumerate(vals)})

    # Make formula
    form_pieces = ([v for v in x] + [v for v in categorical]
                   + ['(1|%s)'%s for s in random_effects if len(s) > 0]
                   + ['(%s)'%s for s in continuous_random_effects if len(s) > 0])
    formula = '%s ~ %s' % (y, ' + '.join(form_pieces))
    print(formula)

    if len(random_effects) == 0 and len(continuous_random_effects) == 0:
        y, X = patsy.dmatrices(formula, sub, return_type='dataframe')

        if link.lower() == 'log':
            linkfn = sm.families.links.log
        else:
            linkfn = sm.families.links.identity

        if family.lower() == 'gamma':
            family = sm.families.Gamma(link=linkfn)
        elif family.lower() == 'gaussian' or family == 'normal':
            family = sm.families.Gaussian(link=linkfn)
        else:
            family = sm.families.Poisson(link=linkfn)

        model = sm.GLM(y, X, family=family)
        glm_results = model.fit()
        print(glm_results.summary2())

    if nonlinear or len(random_effects) > 1 or R:
        rdf = pandas2ri.py2ri(sub)
        pandas2ri.activate()
        base = importr('base')
        # stats = importr('stats')
        afex = importr('afex')

        if nonlinear:
            model = afex.mixed(formula=formula, data=rdf, method='PB', family=family)
        else:
            model = afex.mixed(formula=formula, data=rdf)

        print(base.summary(model))

    return model

def icc(data, icc_type='icc2'):
    """
    Calculate intraclass correlation coefficient for data within
        Brain_Data class
    ICC Formulas are based on:
    Shrout, P. E., & Fleiss, J. L. (1979). Intraclass correlations: uses in
    assessing rater reliability. Psychological bulletin, 86(2), 420.
    icc1:  x_ij = mu + beta_j + w_ij
    icc2/3:  x_ij = mu + alpha_i + beta_j + (ab)_ij + epsilon_ij
    Code modifed from nipype algorithms.icc
    https://github.com/nipy/nipype/blob/master/nipype/algorithms/icc.py
    Args:
        icc_type: type of icc to calculate (icc: voxel random effect,
                icc2: voxel and column random effect, icc3: voxel and
                column fixed effect)
    Returns:
        ICC: intraclass correlation coefficient

    from: https://github.com/cosanlab/nltools/blob/master/nltools/data/brain_data.py
    """

    Y = data  # Transpose?
    [n, k] = Y.shape

    # Degrees of Freedom
    dfc = k - 1
    dfe = (n - 1)*(k - 1)
    dfr = n - 1

    # Sum Square Total
    mean_Y = np.mean(Y)
    SST = ((Y - mean_Y)**2).sum()

    # create the design matrix for the different levels
    x = np.kron(np.eye(k), np.ones((n, 1)))  # sessions
    x0 = np.tile(np.eye(n), (k, 1))  # subjects
    X = np.hstack([x, x0])

    # Sum Square Error
    predicted_Y = np.dot(np.dot(np.dot(X, np.linalg.pinv(np.dot(X.T, X))),
                                X.T), Y.flatten('F'))
    residuals = Y.flatten('F') - predicted_Y
    SSE = (residuals**2).sum()

    MSE = SSE/dfe

    # Sum square column effect - between colums
    SSC = ((np.mean(Y, 0) - mean_Y)**2).sum()*n
    MSC = SSC/dfc/n

    # Sum Square subject effect - between rows/subjects
    SSR = SST - SSC - SSE
    MSR = SSR/dfr

    if icc_type == 'icc1':
        # ICC(2,1) = (mean square subject - mean square error) /
        # (mean square subject + (k-1)*mean square error +
        # k*(mean square columns - mean square error)/n)
        # ICC = (MSR - MSRW) / (MSR + (k-1) * MSRW)
        NotImplementedError("This method isn't implemented yet.")

    elif icc_type == 'icc2':
        # ICC(2,1) = (mean square subject - mean square error) /
        # (mean square subject + (k-1)*mean square error +
        # k*(mean square columns - mean square error)/n)
        ICC = (MSR - MSE)/(MSR + (k - 1)*MSE + k*(MSC - MSE)/n)

    elif icc_type == 'icc3':
        # ICC(3,1) = (mean square subject - mean square error) /
        # (mean square subject + (k-1)*mean square error)
        ICC = (MSR - MSE)/(MSR + (k - 1)*MSE)

    return ICC

def glm(formula, df, family='gaussian', link='identity', dropzeros=True, r=False):
    """
    Apply a GLM using formula to the data in the dataframe data

    :param formula: text formulax
    :param df: pandas dataframe df
    :param family: string denoting what family of functions to use, gaussian, gamma, or poisson
    :param link: link function to use, identity or log
    :param dropzeros: replace zeros with nans if True
    :param r: use the R programming language's version if true
    :return: None
    """

    sub = subformula(formula, df)
    if dropzeros:
        sub.replace(0, np.nan, inplace=True)
    sub.dropna(inplace=True)

    if r:
        pattern = re.compile(r'(\(1|.+\))')
        for an in re.findall(pattern, formula):
            sub[an], _ = pd.factorize(sub[an])

        rdf = pandas2ri.py2ri(sub)
        pandas2ri.activate()
        base = importr('base')
        stats = importr('stats')

        model = stats.glm(formula, data=rdf)
        print(base.summary(model))

    else:
        y, X = patsy.dmatrices(formula, sub, return_type='dataframe')

        if link.lower() == 'log':
            linkfn = sm.families.links.log
        else:
            linkfn = sm.families.links.identity

        if family.lower() == 'gamma':
            family = sm.families.Gamma(link=linkfn)
        elif family.lower() == 'gaussian' or family == 'normal':
            family = sm.families.Gaussian(link=linkfn)
        else:
            family = sm.families.Poisson(link=linkfn)

        model = sm.GLM(y, X, family=family)
        glm_results = model.fit()
        print(glm_results.summary2())
        return model

def permutation_test(x, y, df, n=10000):
    """
    Run a permutation test on a value in a dataframe.

    Parameters
    ----------
    x : str
        name of x parameter
    y : str
        name of y parameter
    df : Pandas DataFrame
        Must contain columns x and y
    n : int
        Number of repetitions

    Returns
    -------
    int
        p-value
    """

    x = df[x].astype(np.float64).as_matrix()
    y = df[y].astype(np.float64).as_matrix()
    val = nancorr(x, y)[0]
    count = 0.0

    for i in range(n):
        rand = nancorr(x, np.random.permutation(y))[0]
        if rand > val:
            count += 1

    return count/n


def nancorr(v1, v2):
    """
    Return the correlation r and p value, ignoring positions with nan.

    :param v1: vector 1
    :param v2: vector 2, of length v1
    :return: (pearson r, p value)
    """

    # p value is defined as
    # t = (r*sqrt(n - 2))/sqrt(1-r*r)
    # where r is correlation coeffcient, n is number of observations, and the T is n - 2 degrees of freedom

    if len(v1) < 2 or len(v2) < 2:
        return (np.nan, np.nan)
    v1, v2 = np.array(v1), np.array(v2)
    nnans = np.bitwise_and(np.isfinite(v1), np.isfinite(v2))
    if np.sum(nnans) == 0:
        return (np.nan, np.nan)
    return pearsonr(v1[nnans], v2[nnans])


def smooth(x, window_len=5, window='flat'):
    """Smooth the data using a window with requested size.

    This method is based on the convolution of a scaled window with the signal.
    The signal is prepared by introducing reflected copies of the signal
    (with the window size) in both ends so that transient parts are minimized
    in the begining and end part of the output signal.

    Parameters
    ----------
    x
        the input signal
    window_len
        the dimension of the smoothing window; should be an odd integer
    window : {'flat', 'hanning', 'hamming', 'bartlett', 'blackman'}
        The type of window. Flat window will produce a moving average smoothing.

    Returns
    -------
        the smoothed signal

    Example
    -------

    t=linspace(-2,2,0.1)
    x=sin(t)+randn(len(t))*0.1
    y=smooth(x)

    see also:

    numpy.hanning, numpy.hamming, numpy.bartlett, numpy.blackman, numpy.convolve
    scipy.signal.lfilter

    NOTE: length(output) != length(input), to correct this: return y[(window_len/2-1):-(window_len/2)] instead of just y.
    """

    if x.ndim != 1:
        raise ValueError('Smooth only accepts 1 dimension arrays.')

    if x.size < window_len:
        raise ValueError('Input vector needs to be bigger than window size.')

    if window_len < 3:
        return x

    if window not in ['flat', 'hanning', 'hamming', 'bartlett', 'blackman']:
        raise ValueError("Window is on of 'flat', 'hanning', 'hamming', 'bartlett', 'blackman'")

    s = np.r_[x[window_len - 1:0:-1], x, x[-2:-window_len - 1:-1]]

    if window == 'flat':  # moving average
        w = np.ones(window_len, 'd')
    else:
        w = eval('np.' + window + '(window_len)')

    y = np.convolve(w/w.sum(), s, mode='valid')
    return y[(window_len/2-1):-(window_len/2)]
