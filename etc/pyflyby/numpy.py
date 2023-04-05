import matplotlib
from   matplotlib               import pyplot
import matplotlib.colors
from   matplotlib.colors        import ColorConverter
from   matplotlib.font_manager  import FontProperties
from   matplotlib.patches       import Rectangle
from   matplotlib.pyplot        import (clf, draw, figure, gca, gcf, ioff,
                                        legend, plot, savefig, scatter, show,
                                        subplot, title, xlabel, ylabel, ylim)
from   matplotlib.ticker        import (Formatter, Locator, NullFormatter,
                                        NullLocator)
import numexpr
import numpy as np, numpy as npy, numpy
from   numpy                    import (Inf, NAN, NaN, abs as aabs, absolute,
                                        add, all as aall, allclose, alltrue,
                                        amax, amin, angle, any as aany,
                                        append as aappend, apply_along_axis,
                                        apply_over_axes, arange, arccos,
                                        arccosh, arcsin, arcsinh, arctan,
                                        arctan2, arctanh, argmax, argmin,
                                        argsort, argwhere, around, array,
                                        array2string, array_equal, array_equiv,
                                        array_repr, array_split, array_str,
                                        asanyarray, asarray, asarray_chkfinite,
                                        ascontiguousarray, asfarray,
                                        asfortranarray, asmatrix, asscalar,
                                        atleast_1d, atleast_2d, atleast_3d,
                                        average, bartlett, base_repr,
                                        binary_repr, bincount, bitwise_and,
                                        bitwise_not, bitwise_or, bitwise_xor,
                                        blackman, bmat, bool8, bool_,
                                        broadcast, broadcast_arrays, byte,
                                        byte_bounds, c_, can_cast, cdouble,
                                        ceil, cfloat, character, chararray,
                                        choose, clip, clongdouble, clongfloat,
                                        column_stack, common_type,
                                        compare_chararrays, compat, complex128,
                                        complex64, complex_, complexfloating,
                                        concatenate, conj, conjugate, convolve,
                                        copy, copysign, corrcoef, correlate,
                                        cos, cosh, cov, cross, csingle,
                                        ctypeslib, cumprod, cumproduct, cumsum,
                                        deg2rad, degrees, diag, diag_indices,
                                        diag_indices_from, diagflat, diagonal,
                                        diff, digitize, disp, divide, dot,
                                        double, dsplit, dstack, dtype, ediff1d,
                                        einsum, emath, empty, empty_like,
                                        equal, exp, exp2, expand_dims, expm1,
                                        extract, eye, fabs,
                                        fastCopyAndTranspose, fill_diagonal,
                                        find_common_type, fix, flatiter,
                                        flatnonzero, fliplr, flipud, float32,
                                        float64, float_, floating, floor,
                                        floor_divide, fmax, fmin, fmod, frexp,
                                        frombuffer, fromfile, fromfunction,
                                        fromiter, frompyfunc, fromregex,
                                        fromstring, gradient, greater,
                                        greater_equal, hamming, hanning,
                                        heaviside, histogram, histogram2d,
                                        histogramdd, hsplit, hstack, hypot,
                                        i0, identity, iinfo, imag, in1d,
                                        index_exp, indices, inexact, inf,
                                        inner, int0, int16, int32, int64,
                                        int8, int_, intc, integer, interp,
                                        intersect1d, intp, invert, ipmt, irr,
                                        iscomplex, iscomplexobj, isfinite,
                                        isfortran, isinf, isnan, isneginf,
                                        isposinf, isreal, isrealobj, isscalar,
                                        issctype, issubclass_, issubdtype,
                                        issubsctype, iterable, ix_, kaiser,
                                        kron, ldexp, left_shift, less,
                                        less_equal, lexsort, linalg, linspace,
                                        little_endian, loadtxt, log,
                                        log as logarithm, log10, log1p, log2,
                                        logaddexp, logaddexp2, logical_and,
                                        logical_not, logical_or, logical_xor,
                                        logspace, longcomplex, longdouble,
                                        longfloat, longlong, mafromtxt,
                                        mask_indices, mat, matrix, maximum,
                                        mean, median, memmap, meshgrid, mgrid,
                                        minimum, mintypecode, mirr, mod, modf,
                                        msort, multiply, nan, nan_to_num,
                                        nanargmax, nanargmin, nanmax, nanmin,
                                        nansum, nbytes, ndarray, ndenumerate,
                                        ndim, ndindex, negative, newaxis,
                                        newbuffer, nextafter, nonzero,
                                        not_equal, nper, npv, number, object0,
                                        object_, ogrid, ones, ones_like,
                                        outer, packbits, pi, piecewise,
                                        pkgload, place, pmt, poly, poly1d,
                                        polyadd, polyder, polydiv, polyfit,
                                        polyint, polymul, polynomial, polysub,
                                        polyval, power, ppmt, prod, product,
                                        ptp, putmask, pv, r_, rad2deg,
                                        radians, rank, rate, ravel, real,
                                        real_if_close, recarray, recfromcsv,
                                        recfromtxt, reciprocal, record,
                                        remainder, repeat, reshape, resize,
                                        restoredot, right_shift, rint, roll,
                                        rollaxis, roots, rot90, round, round_,
                                        row_stack, s_, searchsorted,
                                        select as aselect, setbufsize,
                                        setdiff1d, setxor1d, shape, short,
                                        show_config, sign, signbit,
                                        signedinteger, sin, sinc, single,
                                        singlecomplex, sinh, size as asize,
                                        sometrue, sort as asort, sort,
                                        sort_complex, spacing, split, sqrt,
                                        square, squeeze, std, str_, string0,
                                        string_, subtract, sum, swapaxes, take,
                                        tan, tanh, tensordot, testing, tile,
                                        trace, transpose, trapz, tri, tril,
                                        tril_indices, tril_indices_from,
                                        trim_zeros, triu, triu_indices,
                                        triu_indices_from, true_divide, trunc,
                                        ubyte, ufunc, uint, uint0, uint16,
                                        uint32, uint64, uint8, uintc, uintp,
                                        ulonglong, unicode0, unicode_, union1d,
                                        unique, unpackbits, unravel_index,
                                        unsignedinteger, unwrap, ushort,
                                        vander, var, vdot, vectorize, void,
                                        void0, vsplit, vstack, where, zeros,
                                        zeros_like)
from   numpy.core.umath_tests   import inner1d
from   numpy.fft                import (fft, fft2, fftn, ifft, ifft2, ifftn,
                                        irfft, irfft2, irfftn, rfft, rfft2,
                                        rfftn)
from   numpy.lib                import recfunctions as recf, recfunctions
from   numpy.lib.stride_tricks  import as_strided
import numpy.linalg
from   numpy.linalg             import cholesky, det, eigh, inv, pinv, svd
from   numpy.random             import (normal, rand, randint, randn,
                                        random as arandom, shuffle)
import numpy.testing
import numpy.version
import pandas, pandas as pd
from   pandas                   import DataFrame, Series, TimeSeries
import pylab as pl, pylab
import scipy
from   scipy                    import integrate, optimize, special, stats
import scipy.cluster.hierarchy
import scipy.integrate
import scipy.interpolate
from   scipy.interpolate        import InterpolatedUnivariateSpline, interp1d
import scipy.linalg
import scipy.optimize
from   scipy.optimize           import (curve_fit, fmin_l_bfgs_b, fsolve,
                                        leastsq)
from   scipy.optimize.zeros     import bisect
import scipy.special
from   scipy.special            import gamma, gammainc, gammaincinv, ndtri
import scipy.stats
from   scipy.stats              import (chisqprob, distributions,
                                        scoreatpercentile, uniform)
from   scipy.stats.distributions \
                                import norm
