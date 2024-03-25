import time
import functools
import gc

import jax
from jax import numpy as jnp
from jax import random
from matplotlib import pyplot as plt
import bartz

# Devices to benchmark on
devices = {
    'cpu': jax.devices('cpu')[0],
    # 'gpu': jax.devices('gpu')[0],
}

# BART config
ntree = 200
mcmc_iterations = 1
nchains = 8

# DGP definition
nvec = [ # number of datapoints
    100,
    200,
    500,
    1000,
    2000,
    5000,
    10_000,
    20_000,
    50_000,
    100_000,
    200_000,
    500_000,
    1000_000,
    2000_000,
    5000_000,
    10_000_000,
    20_000_000,
    50_000_000,
    100_000_000,
]
p = 10 # number of covariates
sigma = 0.1 # noise standard deviation
def f(x): # conditional mean
    T = 2
    return jnp.sum(jnp.cos(2 * jnp.pi / T * x), axis=0)
def gen_X(key, p, n):
    return random.uniform(key, (p, n), float, -2, 2)
def gen_y(key, X):
    return f(X) + sigma * random.normal(key, X.shape[1:])

# random seed
key = random.key(202403241634)

class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self
    def __exit__(self, *_):
        self.time = time.perf_counter() - self.start

times = {}
for n in nvec:

    print(f'n = {n}', end='', flush=True)

    # generate data
    key, subkey1, subkey2, subkey3 = random.split(key, 4)
    X = gen_X(subkey1, p, n)
    y = f(X) + sigma * random.normal(subkey2, (n,))

    # build initial mcmc state
    state = bartz.BART.gbart(X, y, ntree=ntree, nskip=0, ndpost=0, seed=0)._mcmc_state

    # clean up memory
    del X, y
    gc.collect()

    # repeat for each device
    for label, device in devices.items():

        # commit inputs to the target device
        keys = random.split(subkey3, nchains)
        state, keys = jax.device_put((state, keys), device)

        # pre-compile mcmc loop
        @jax.jit
        @functools.partial(jax.vmap, in_axes=(None, 0))
        def task(state, key):
            return bartz.mcmcloop.run_mcmc(state, 0, mcmc_iterations, 1, lambda **_: None, key)
        task = task.lower(state, keys).compile()

        # clock
        with Timer() as timer:
            jax.block_until_ready(task(state, keys))

        # save result
        times.setdefault(label, []).append(timer.time)
        print(f', {label}: {timer.time:.2g}s', end='', flush=True)

        # clean up memory
        del state
        gc.collect()

    print()

def textbox(ax, text, loc='lower left', **kw):
    """
    Draw a box with text on a matplotlib plot.
    
    Parameters
    ----------
    ax : matplotlib axis
        The plot where the text box is drawn.
    text : str
        The text.
    loc : str
        The location of the box. Format: 'lower/center/upper left/center/right'.
    
    Keyword arguments
    -----------------
    Additional keyword arguments are passed to ax.annotate. If you pass a
    dictionary for the `bbox` argument, the defaults are updated instead of
    resetting the bounding box properties.
    
    Return
    ------
    The return value is that from ax.annotate.
    """
    
    M = 8
    locparams = {
        'lower left'   : dict(xy=(0  , 0  ), xytext=( M,  M), va='bottom', ha='left'  ),
        'lower center' : dict(xy=(0.5, 0  ), xytext=( 0,  M), va='bottom', ha='center'),
        'lower right'  : dict(xy=(1  , 0  ), xytext=(-M,  M), va='bottom', ha='right' ),
        'center left'  : dict(xy=(0  , 0.5), xytext=( M,  0), va='center', ha='left'  ),
        'center center': dict(xy=(0.5, 0.5), xytext=( 0,  0), va='center', ha='center'),
        'center right' : dict(xy=(1  , 0.5), xytext=(-M,  0), va='center', ha='right' ),
        'upper left'   : dict(xy=(0  , 1  ), xytext=( M, -M), va='top'   , ha='left'  ),
        'upper center' : dict(xy=(0.5, 1  ), xytext=( 0, -M), va='top'   , ha='center'),
        'upper right'  : dict(xy=(1  , 1  ), xytext=(-M, -M), va='top'   , ha='right' ),
    }
    
    kwargs = dict(
        xycoords='axes fraction',
        textcoords='offset points',
        bbox=dict(
            facecolor='white',
            alpha=0.75,
            edgecolor='#ccc',
            boxstyle='round'
        ),
    )
    kwargs.update(locparams[loc])
    
    newkw = dict(kw)
    for k, v in kw.items():
        if isinstance(v, dict) and isinstance(kwargs.get(k, None), dict):
            kwargs[k].update(v)
            newkw.pop(k)
    kwargs.update(newkw)
    
    return ax.annotate(text, **kwargs)

# plot execution time
fig, ax = plt.subplots(num='benchmark-device', clear=True, layout='constrained')

times_array = jnp.array(list(times.values())).T
ax.plot(nvec, times_array, label=list(times.keys()))
ax.legend(loc='upper left')
ax.set(xlabel='n', ylabel='time (s)', xscale='log', yscale='log')
ax.grid(linestyle='--')
ax.grid(which='minor', linestyle=':')
textbox(ax, f"""\
p = {p}
ntree = {ntree}
nchains = {nchains}
mcmc_iterations = {mcmc_iterations}""", loc='lower right')

fig.show()
