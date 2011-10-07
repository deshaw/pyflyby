import matplotlib
from   matplotlib               import (cm, scale as mscale,
                                        transforms as mtransforms)
import matplotlib.colors
from   matplotlib.colors        import ColorConverter
from   matplotlib.font_manager  import FontProperties
from   matplotlib.patches       import Rectangle
from   matplotlib.pyplot        import clf, ioff, legend, title, xlabel, ylabel
from   matplotlib.ticker        import (Formatter, Locator, NullFormatter,
                                        NullLocator)
import numpy as np, numpy
from   numpy                    import (Inf, NAN, NaN, add, allclose, arange,
                                        argsort, array, asarray, asmatrix,
                                        asscalar, average, clip, concatenate,
                                        cumsum, diag, diff, digitize, divide,
                                        dot, double, dtype, empty, empty_like,
                                        exp, eye, float64, hstack, identity,
                                        iinfo, inf, inner, int32, int64,
                                        integer, intersect1d, isfinite, isnan,
                                        isscalar, kron, linalg, loadtxt, log,
                                        log as logarithm, logical_not, matrix,
                                        mean, median, mod, multiply, nan,
                                        nan_to_num, nansum, ndarray, newaxis,
                                        ones, ones_like, prod, r_, ravel,
                                        reshape, rot90, searchsorted, sin,
                                        sinh, sort, sqrt, squeeze, std, tan,
                                        tanh, tile, var, vstack, where, zeros,
                                        zeros_like)
from   numpy.core               import umath_tests
from   numpy.core.umath_tests   import inner1d
from   numpy.fft                import fft, ifft
from   numpy.lib                import recfunctions as recf, recfunctions
from   numpy.lib.stride_tricks  import as_strided
import numpy.linalg
from   numpy.linalg             import cholesky, det, eigh, inv, pinv, svd
from   numpy.random             import normal, rand, randint, randn, shuffle
import numpy.testing
import numpy.version
import pylab as pl, pylab
from   pylab                    import figure, grid, plot, savefig, ylim
import scipy
from   scipy                    import integrate, optimize, special, stats
import scipy.cluster.hierarchy
import scipy.integrate
import scipy.interpolate
from   scipy.interpolate        import InterpolatedUnivariateSpline, interp1d
import scipy.linalg
import scipy.optimize
from   scipy.optimize           import fmin_l_bfgs_b, fsolve, leastsq
from   scipy.optimize.zeros     import bisect
from   scipy.signal             import convolve
import scipy.special
from   scipy.special            import gamma, gammainc, gammaincinv, ndtri
import scipy.stats
from   scipy.stats              import (distributions, scoreatpercentile,
                                        uniform)
from   scipy.stats.distributions \
                                import norm
