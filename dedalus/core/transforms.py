

import numpy as np
from scipy import fftpack
import dedalus_sphere

from . import basis
from ..tools import jacobi
from ..tools.array import apply_matrix, axslice
from ..tools.cache import CachedAttribute
from ..tools.cache import CachedMethod


def register_transform(basis, name):
    """Decorator to add transform to basis class dictionary."""
    def wrapper(cls):
        if not hasattr(basis, 'transforms'):
            basis.transforms = {}
        basis.transforms[name] = cls
        return cls
    return wrapper


def reduced_view_3(data, axis):
    shape = data.shape
    N0 = int(np.prod(shape[:axis]))
    N1 = shape[axis]
    N2 = int(np.prod(shape[axis+1:]))
    return data.reshape((N0, N1, N2))


def reduced_view_4(data, axis):
    shape = data.shape
    N0 = int(np.prod(shape[:axis]))
    N1 = shape[axis]
    N2 = shape[axis+1]
    N3 = int(np.prod(shape[axis+2:]))
    return data.reshape((N0, N1, N2, N3))

def reduced_view_5(data, axis):
    shape = data.shape
    N0 = int(np.prod(shape[:axis]))
    N1 = shape[axis]
    N2 = shape[axis+1]
    N3 = shape[axis+2]
    N4 = int(np.prod(shape[axis+3:]))
    return data.reshape((N0, N1, N2, N3, N4))

class Transform:
    pass


class PolynomialTransform(Transform):

    def __init__(self, grid_size, coeff_size):
        self.grid_size = self.N1G = grid_size
        self.coeff_size = self.N1C = coeff_size

    # def __init__(self, basis, coeff_shape, dtype, axis, scale):
    #     self.basis = basis
    #     self.dtype = dtype
    #     self.coeff_shape = coeff_shape
    #     self.axis = axis
    #     self.scale = scale

    #     # Treat complex arrays as higher dimensional real arrays
    #     if self.dtype == np.complex128:
    #         coeff_shape = list(coeff_shape) + [2]

    #     self.N0 = N0 = np.prod(coeff_shape[:axis], dtype=int)
    #     self.N1C = N1C = coeff_shape[axis]
    #     self.N1G = N1G = int(self.N1C * scale)
    #     self.N2 = N2 = np.prod(coeff_shape[axis+1:], dtype=int)

    #     self.gdata_reduced = np.zeros(shape=[N0, N1G, N2], dtype=np.float64)
    #     self.cdata_reduced = np.zeros(shape=[N0, N1C, N2], dtype=np.float64)


    # def check_arrays(self, cdata, gdata, axis, scale=None):
    #     """
    #     Verify provided arrays sizes and dtypes are correct.
    #     Build compliant arrays if not provided.

    #     """

    #     if cdata is None:
    #         # Build cdata
    #         cshape = list(gdata.shape)
    #         cshape[axis] = self.coeff_size
    #         cdata = fftw.create_array(cshape, self.coeff_dtype)
    #     else:
    #         # Check cdata
    #         if cdata.shape[axis] != self.space.coeff_size:
    #             raise ValueError("cdata does not match coeff_size")
    #         if cdata.dtype != self.domain.dtype:
    #             raise ValueError("cdata does not match coeff_dtype")

    #     if scale:
    #         grid_size = self.space.grid_size(scale)

    #     if gdata is None:
    #         # Build gdata
    #         gshape = list(cdata.shape)
    #         gshape[axis] = grid_size
    #         gdata = fftw.create_array(gshape, self.grid_dtype)
    #     else:
    #         # Check gdata
    #         if scale and (gdata.shape[axis] != grid_size):
    #             raise ValueError("gdata does not match scaled grid_size")
    #         if gdata.dtype != self.domain.dtype:
    #             raise ValueError("gdata does not match grid_dtype")

    #     return cdata, gdata

    @staticmethod
    def resize_reduced(data_in, data_out):
        """Resize data by padding/truncation."""
        size_in = data_in.shape[1]
        size_out = data_out.shape[1]
        if size_in < size_out:
            # Pad with zeros at end of data
            np.copyto(data_out[:, :size_in, :], data_in)
            np.copyto(data_out[:, size_in:, :], 0)
        elif size_in > size_out:
            # Truncate higher order modes at end of data
            np.copyto(data_out, data_in[:, :size_out, :])
        else:
            np.copyto(data_out, data_in)

    def forward(self, gdata, cdata, axis):
        # Make reduced view into input arrays
        self.gdata_reduced = reduced_view_3(gdata, axis)
        self.cdata_reduced = reduced_view_3(cdata, axis)
        #self.gdata_reduced.data = gdata
        #self.cdata_reduced.data = cdata
        # Transform reduced arrays
        self.forward_reduced()

    def backward(self, cdata, gdata, axis):
        # Make reduced view into input arrays
        self.gdata_reduced = reduced_view_3(gdata, axis)
        self.cdata_reduced = reduced_view_3(cdata, axis)
        # self.cdata_reduced.data = cdata
        # self.gdata_reduced.data = gdata
        # Transform reduced arrays
        self.backward_reduced()


class SeparableTransform(Transform):
    """Abstract base class for transforms that only apply to one dimension, independent of all others."""

    def forward(self, gdata, cdata, axis):
        """Apply forward transform along specified axis."""
        # Subclasses must implement
        raise NotImplementedError

    def backward(self, cdata, gdata, axis):
        """Apply backward transform along specified axis."""
        # Subclasses must implement
        raise NotImplementedError


class MatrixTransform(SeparableTransform):
    """Separable matrix-multiplication transforms."""

    def forward(self, gdata, cdata, axis):
        """Apply forward transform along specified axis."""
        apply_matrix(self.forward_matrix, gdata, axis=axis, out=cdata)

    def backward(self, cdata, gdata, axis):
        """Apply backward transform along specified axis."""
        apply_matrix(self.backward_matrix, cdata, axis=axis, out=gdata)

    @CachedAttribute
    def forward_matrix(self):
        # Subclasses must implement
        raise NotImplementedError

    @CachedAttribute
    def backward_matrix(self):
        # Subclasses must implement
        raise NotImplementedError


@register_transform(basis.Jacobi, 'matrix')
@register_transform(basis.SphericalShellRadialBasis, 'matrix')
class JacobiMatrixTransform(MatrixTransform):
    """Jacobi polynomial transforms."""

    def __init__(self, grid_size, coeff_size, a, b, a0, b0):
        self.grid_size = grid_size
        self.coeff_size = coeff_size
        self.a = a
        self.b = b
        self.a0 = a0
        self.b0 = b0

    @CachedAttribute
    def forward_matrix(self):
        N = self.grid_size
        M = self.coeff_size
        a, a0 = self.a, self.a0
        b, b0 = self.b, self.b0
        # Gauss quadrature with base polynomials
        base_grid = jacobi.build_grid(N, a=a0, b=b0)
        base_polynomials = jacobi.build_polynomials(M, a0, b0, base_grid)
        base_weights = jacobi.build_weights(N, a=a0, b=b0)
        base_transform = (base_polynomials * base_weights)
        # Zero higher coefficients for transforms with grid_size < coeff_size
        base_transform[N:, :] = 0
        # Spectral conversion
        if (a == a0) and (b == b0):
            forward_matrix = base_transform
        else:
            conversion = jacobi.conversion_matrix(M, a0, b0, a, b)
            forward_matrix = conversion @ base_transform
        return np.asarray(forward_matrix, order='C')

    @CachedAttribute
    def backward_matrix(self):
        N = self.grid_size
        M = self.coeff_size
        a, a0 = self.a, self.a0
        b, b0 = self.b, self.b0
        # Polynomial recursion using base grid
        base_grid = jacobi.build_grid(N, a=a0, b=b0)
        polynomials = jacobi.build_polynomials(M, a, b, base_grid)
        # Zero higher polynomials for transforms with grid_size < coeff_size
        polynomials[N:, :] = 0
        return np.asarray(polynomials.T, order='C')


class FourierTransform(SeparableTransform):
    """
    Complex Fourier transform with unit-amplitude normalization:

    Forward transform:
        F(k) = (1/N) \sum_{x=0}^{N-1} f(x) \exp(-2 \pi i k x / N)

    Backward transform:
        f(x) = \sum_{k=-K}^{K} F(k) \exp(2 \pi i k x / N)
        K = (M - 1) // 2

    Notes:
        - Nyquist mode is zeroed in both directions.
        - Coefficient ordering is [0, 1, 2, ..., K, K+1, -K, -K+1, ..., -1].
    """

    def __init__(self, grid_size, coeff_size):
        self.N = grid_size
        self.M = coeff_size

    @property
    def wavenumbers(self):
        M = self.M
        K = np.arange(M)
        # Wrap around Nyquist mode
        KN = (M + 1) // 2
        return (K + KN - 1) % M - (KN - 1)

    @staticmethod
    def resize_coeffs(data_in, data_out, axis, rescale=1):
        """Resize coefficients by padding/truncation."""
        data_in_reduced = reduced_view_3(data_in, axis)
        data_out_reduced = reduced_view_3(data_out, axis)
        K_in = (data_in.shape[axis] - 1) // 2
        K_out = (data_out.shape[axis] - 1) // 2
        K = min(K_in, K_out)
        np.multiply(data_in_reduced[:, :K+1], rescale, out=data_out_reduced[:, :K+1])
        data_out_reduced[:, K+1:-K] = 0
        np.multiply(data_in_reduced[:, -K:], rescale, out=data_out_reduced[:, -K:])


@register_transform(basis.ComplexFourier, 'matrix')
class FourierMatrixTransform(FourierTransform, MatrixTransform):
    """Complex Fourier matrix transform."""

    @CachedAttribute
    def forward_matrix(self):
        K = self.wavenumbers[:, None]
        X = np.arange(self.N)[None, :]
        dX = self.N / 2 / np.pi
        quadrature = np.exp(-1j*K*X/dX) / self.N
        # Zero Nyquist and higher modes for transforms with grid_size <= coeff_size
        KN = (min(self.M, self.N) + 1) // 2
        quadrature *= (np.abs(K) < KN)
        return np.asarray(quadrature, order='C')

    @CachedAttribute
    def backward_matrix(self):
        K = self.wavenumbers[None, :]
        X = np.arange(self.N)[:, None]
        dX = self.N / 2 / np.pi
        functions = np.exp(1j*K*X/dX)
        # Zero Nyquist and higher modes for transforms with grid_size <= coeff_size
        KN = (min(self.M, self.N) + 1) // 2
        functions *= (np.abs(K) < KN)
        return np.asarray(functions, order='C')


@register_transform(basis.ComplexFourier, 'ScipyFFT')
class ScipyFFT(FourierTransform):
    """Complex FFT using Scipy's FFTPACK."""

    def forward(self, gdata, cdata, axis):
        """Apply forward transform along specified axis."""
        # Call FFT
        temp = fftpack.fft(gdata, axis=axis)
        # Resize and rescale for unit-amplitude normalization
        self.resize_coeffs(temp, cdata, axis, rescale=1/self.N)

    def backward(self, cdata, gdata, axis):
        """Apply backward transform along specified axis."""
        # Resize and rescale for unit-amplitude normalization
        # Need temporary to avoid overwriting problems
        temp = np.empty_like(gdata)
        self.resize_coeffs(cdata, temp, axis, rescale=self.N)
        # Call FFT
        gdata[:] = fftpack.ifft(temp, axis=axis)


class ScipyDST(PolynomialTransform):

    def forward_reduced(self):
        # DST-II transform from interior points
        temp = fftpack.dst(self.gdata_reduced, type=2, axis=1)
        # Rescale as sinusoid amplitudes
        temp[:, -1, :] *= 0.5
        temp *= (1 / self.N1G)
        # Resize
        self.resize_reduced(temp, self.cdata_reduced)

    def backward_reduced(self):
        # Resize into gdata for memory efficiency
        self.resize_reduced(self.cdata_reduced, self.gdata_reduced)
        # Rescale from sinusoid amplitudes
        self.gdata_reduced[:, :-1, :] *= 0.5
        # DST-III transform to interior points
        temp = fftpack.dst(self.gdata_reduced, type=3, axis=1)
        np.copyto(self.gdata_reduced, temp)


#@register_transform(basis.Sine, 'scipy')
class ScipySineTransform(ScipyDST):

    def forward_reduced(self):
        super().forward_reduced()
        # Shift data, adding zero mode and dropping Nyquist
        start = self.cdata_reduced[:, :-1, :]
        shift = self.cdata_reduced[:, 1:, :]
        np.copyto(shift, start)
        self.cdata_reduced[:, 0, :] = 0

    def backward_reduced(self):
        # Unshift data, adding Nyquist mode and dropping zero
        start = self.cdata_reduced[:, :-1, :]
        shift = self.cdata_reduced[:, 1:, :]
        np.copyto(start, shift)
        self.cdata_reduced[:, -1, :] = 0
        super().backward_reduced()


# @register_transform(basis.ChebyshevU, 'scipy')
# class ScipyChebyshevUTransform(ScipyDST):
#     """
#     f(x) = c_n U_n(x)
#     f(x) sin(θ) = c_n sin(θ) U_n(x)
#                 = c_n sin((n+1)θ)

#     c_n are the U_n coefficients of f(x)
#                 sine coefficients of f(x) sin(θ)
#     """

#     def forward_reduced(self):
#         self.gdata_reduced *= sin_θ
#         super().forward_reduced()

#     def backward_reduce(self):
#         super().backward_reduced()
#         self.gdata_reduced *= (1 / sin_θ)


# cdef class FFTWSineTransform:

#     @CachedMethod
#     def _fftw_dst_setup(self, dtype, gshape, axis):
#         """Build FFTW DST plan and temporary array."""
#         flags = ['FFTW_'+FFTW_RIGOR.upper()]
#         logger.debug("Building FFTW DST plan for (dtype, gshape, axis) = (%s, %s, %s)" %(dtype, gshape, axis))
#         plan = fftw.DiscreteSineTransform(dtype, gshape, axis, flags=flags)
#         temp = fftw.create_array(gshape, dtype)
#         return plan, temp

#     def _forward_fftw(self, gdata, cdata, axis, scale):
#         """Forward transform using FFTW DCT."""
#         cdata, gdata = self.check_arrays(cdata, gdata, axis)
#         plan, temp = self._fftw_dst_setup(gdata.dtype, gdata.shape, axis)
#         plan.forward(gdata, temp)
#         self._forward_dst_scaling(temp, axis)
#         self._resize_coeffs(temp, cdata, axis)
#         return cdata

#     def _backward_fftw(self, cdata, gdata, axis, scale):
#         """Backward transform using FFTW IDCT."""
#         cdata, gdata = self.check_arrays(cdata, gdata, axis, scale)
#         plan, temp = self._fftw_dst_setup(gdata.dtype, gdata.shape, axis)
#         self._resize_coeffs(cdata, temp, axis)
#         self._backward_dst_scaling(temp, axis)
#         plan.backward(temp, gdata)
#         return gdata


#@register_transform(basis.Cosine, 'scipy')
class ScipyDCT(PolynomialTransform):

    def forward_reduced(self):
        # DCT-II transform from interior points
        temp = fftpack.dct(self.gdata_reduced, type=2, axis=1)
        # Rescale as sinusoid amplitudes
        temp[:, 0, :] *= 0.5
        temp *= (1 / self.N1G)
        # Resize
        self.resize_reduced(temp, self.cdata_reduced)

    def backward_reduced(self):
        # Resize into gdata for memory efficiency
        self.resize_reduced(self.cdata_reduced, self.gdata_reduced)
        # Rescale from sinusoid amplitudes
        self.gdata_reduced[:, 1:, :] *= 0.5
        # DCT-III transform to interior points
        temp = fftpack.dct(self.gdata_reduced, type=3, axis=1)
        np.copyto(self.gdata_reduced, temp)


# @register_transform(basis.ChebyshevT, 'scipy')
# class ScipyChebyshevTTransform(ScipyDCT):

#     def forward_reduced(self):
#         super().forward_reduced()
#         # Negate odd modes for natural grid ordering
#         self.cdata_reduced[:, 1::2, :] *= -1

#     def backward_reduced(self):
#         # Negate odd modes for natural grid ordering
#         self.cdata_reduced[:, 1::2, :] *= -1
#         super().backward_reduced()


# class FFTWCosine:

#     @CachedMethod
#     def _fftw_dct_setup(self, dtype, gshape, axis):
#         """Build FFTW DCT plan and temporary array."""
#         flags = ['FFTW_'+FFTW_RIGOR.upper()]
#         logger.debug("Building FFTW DCT plan for (dtype, gshape, axis) = (%s, %s, %s)" %(dtype, gshape, axis))
#         plan = fftw.DiscreteCosineTransform(dtype, gshape, axis, flags=flags)
#         temp = fftw.create_array(gshape, dtype)
#         return plan, temp

#     def _forward_fftw(self, gdata, cdata, axis, scale):
#         """Forward transform using FFTW DCT."""
#         cdata, gdata = self.check_arrays(cdata, gdata, axis)
#         plan, temp = self._fftw_dct_setup(gdata.dtype, gdata.shape, axis)
#         plan.forward(gdata, temp)
#         self._forward_dct_scaling(temp, axis)
#         self._resize_coeffs(temp, cdata, axis)
#         return cdata

#     def _backward_fftw(self, cdata, gdata, axis, scale):
#         """Backward transform using FFTW IDCT."""
#         cdata, gdata = self.check_arrays(cdata, gdata, axis, scale)
#         plan, temp = self._fftw_dct_setup(gdata.dtype, gdata.shape, axis)
#         self._resize_coeffs(cdata, temp, axis)
#         self._backward_dct_scaling(temp, axis)
#         plan.backward(temp, gdata)
#         return gdata


class ScipyRFFT(PolynomialTransform):
    """
    Mode order: [cos 0, -sin 0, cos 1, -sin 1, ...]

    (a + bi) e^{ikx}
    (a + bi) (cos(kx) + i sin(kx))
    a cos(kx) - b sin(kx) + i (...)
    """

    def forward_reduced(self):
        # RFFT
        temp = fftpack.rfft(self.gdata_reduced, axis=1)
        # Rescale as sinusoid amplitudes
        scaling = np.ones(self.N1G) / self.N1G
        scaling[1:-1] *= 2
        #scaling[2::2] *= -1
        temp *= scaling[None, :, None]
        # Resize
        self.resize_reduced(temp, self.cdata_reduced)

    def backward_reduced(self):
        # Resize into gdata for memory efficiency
        self.resize_reduced(self.cdata_reduced, self.gdata_reduced)
        # Rescale from sinusoid amplitudes
        scaling = np.ones(self.N1G) / self.N1G
        scaling[1:-1] *= 2
        #scaling[2::2] *= -1
        self.gdata_reduced *= 1 / scaling[None, :, None]
        # IRFFT
        temp = fftpack.irfft(self.gdata_reduced, axis=1)
        np.copyto(self.gdata_reduced, temp)


@register_transform(basis.RealFourier, 'ScipyRFFT')
class ScipyFourierTransform(ScipyRFFT):

    def forward_reduced(self):
        super().forward_reduced()
        # Shift data, adding zero sine mode and dropping Nyquist cosine
        start = self.cdata_reduced[:, 1:-1, :]
        shift = self.cdata_reduced[:, 2:, :]
        np.copyto(shift, start)
        self.cdata_reduced[:, 1, :] = 0

    def backward_reduced(self):
        # Unshift data, adding Nyquist cosine and dropping zero sine
        start = self.cdata_reduced[:, 1:-1, :]
        shift = self.cdata_reduced[:, 2:, :]
        np.copyto(start, shift)
        self.cdata_reduced[:, -1, :] = 0
        super().backward_reduced()


def reduce_array(data, axis):
    """Return reduced 3D view of array collapsed above and below specified axis."""
    N0 = int(np.prod(data.shape[:axis]))
    N1 = data.shape[axis]
    N2 = int(np.prod(data.shape[axis+1:]))
    return data.reshape((N0, N1, N2))

def forward_DFT(gdata, cdata, axis):
    gdata_reduced = reduce_array(gdata, axis)
    cdata_reduced = reduce_array(cdata, axis)
    # Raw transform
    temp = np.fft.fft(gdata_reduced, axis=1)
    PolynomialTransform.resize_reduced(temp, cdata_reduced)
    # Rescale to sinusoid amplitudes
    cdata_reduced /= gdata_reduced.shape[1]

def backward_DFT(cdata, gdata, axis):
    gdata_reduced = reduce_array(gdata, axis)
    cdata_reduced = reduce_array(cdata, axis)
    # Rescale from sinusoid amplitudes
    cdata_reduced *= gdata_reduced.shape[1]
    # Raw transform
    PolynomialTransform.resize_reduced(cdata_reduced, gdata_reduced)
    temp = np.fft.ifft(gdata_reduced, axis=1)
    np.copyto(gdata_reduced, temp)



# class FFTWFourierTransform:

#     @CachedMethod
#     def _fftw_setup(self, dtype, gshape, axis):
#         """Build FFTW plans and temporary arrays."""
#         # Note: regular method used to cache through basis instance

#         logger.debug("Building FFTW FFT plan for (dtype, gshape, axis) = (%s, %s, %s)" %(dtype, gshape, axis))
#         flags = ['FFTW_'+FFTW_RIGOR.upper()]
#         plan = fftw.FourierTransform(dtype, gshape, axis, flags=flags)
#         temp = fftw.create_array(plan.cshape, np.complex128)
#         if dtype == np.float64:
#             resize_coeffs = self._resize_real_coeffs
#         elif dtype == np.complex128:
#             resize_coeffs = self._resize_complex_coeffs

#         return plan, temp, resize_coeffs

#     def _forward_fftw(self, gdata, cdata, axis, meta):
#         """Forward transform using FFTW FFT."""

#         cdata, gdata = self.check_arrays(cdata, gdata, axis)
#         plan, temp, resize_coeffs = self._fftw_setup(gdata.dtype, gdata.shape, axis)
#         # Execute FFTW plan
#         plan.forward(gdata, temp)
#         # Scale FFT output to mode amplitudes
#         temp *= 1 / gdata.shape[axis]
#         # Pad / truncate coefficients
#         resize_coeffs(temp, cdata, axis, gdata.shape[axis])

#         return cdata

#     def _backward_fftw(self, cdata, gdata, axis, meta):
#         """Backward transform using FFTW IFFT."""

#         cdata, gdata = self.check_arrays(cdata, gdata, axis, meta)
#         plan, temp, resize_coeffs = self._fftw_setup(gdata.dtype, gdata.shape, axis)
#         # Pad / truncate coefficients
#         resize_coeffs(cdata, temp, axis, gdata.shape[axis])
#         # Execute FFTW plan
#         plan.backward(temp, gdata)

#         return gdata


class NonSeparableTransform(Transform):

    def __init__(self, grid_shape, coeff_size, axis, dtype):

        self.N2g = grid_shape[axis]
        self.N2c = coeff_size

#    @staticmethod
#    def resize_reduced(data_in, data_out):
#        """Resize data by padding/truncation."""
#        size_in = data_in.shape[2]
#        size_out = data_out.shape[2]
#        if size_in < size_out:
#            # Pad with zeros at end of data
#            np.copyto(data_out[:, :, :size_in, :], data_in)
#            np.copyto(data_out[:, :, size_in:, :], 0)
#        elif size_in > size_out:
#            # Truncate higher order modes at end of data
#            np.copyto(data_out, data_in[:, :, :size_out, :])
#        else:
#            np.copyto(data_out, data_in)

    def forward(self, gdata, cdata, axis):
        # Make reduced view into input arrays
        gdata = reduced_view_4(gdata, axis-1)
        cdata = reduced_view_4(cdata, axis-1)
        # Transform reduced arrays
        self.forward_reduced(gdata, cdata)

    def backward(self, cdata, gdata, axis):
        # Make reduced view into input arrays
        cdata = reduced_view_4(cdata, axis-1)
        gdata = reduced_view_4(gdata, axis-1)
        # Transform reduced arrays
        self.backward_reduced(cdata, gdata)


@register_transform(basis.SpinWeightedSphericalHarmonics, 'matrix')
class SWSHColatitudeTransform(NonSeparableTransform):
    """
    TODO:
        - Remove dependence on grid_shape?
    """

    def __init__(self, grid_shape, basis_shape, axis, m_maps, s, dtype=np.complex128):
        self.Nphi = basis_shape[0]
        self.Lmax = basis_shape[1] - 1
        super().__init__(grid_shape, self.Lmax+1, axis, dtype)
        self.m_maps = m_maps
        self.s = s
        self.shift = max(0, self.Lmax + 1 - self.Nphi//2)

    def forward_reduced(self, gdata, cdata):
        # local_m = self.local_m
        # if gdata.shape[1] != len(local_m): # do we want to do this check???
        #     raise ValueError("gdata.shape[1]: %i, len(local_m): %i" %(gdata.shape[1], len(local_m)))
        m_matrices = self._forward_SWSH_matrices
        shift = self.shift
        Nphi = self.Nphi
        Lmax = self.Lmax
        for m, mg_slice, mc_slice, ell_slice in self.m_maps:
            # Skip transforms when |m| > Lmax
            if np.abs(m) <= Lmax:
                # Use rectangular transform matrix, padded with zeros when Lmin > abs(m)
                grm = gdata[:, mg_slice, :, :]
                crm = cdata[:, mc_slice, ell_slice, :]
                apply_matrix(m_matrices[m], grm, axis=2, out=crm)

    def backward_reduced(self, cdata, gdata):
        # local_m = self.local_m
        # if gdata.shape[1] != len(local_m): # do we want to do this check???
        #     raise ValueError("gdata.shape[1]: %i, len(local_m): %i" %(gdata.shape[1], len(local_m)))
        m_matrices = self._backward_SWSH_matrices
        shift = self.shift
        Nphi = self.Nphi
        Lmax = self.Lmax
        for m, mg_slice, mc_slice, ell_slice in self.m_maps:
            if np.abs(m) > Lmax:
                # Write zeros because they'll be used by the inverse azimuthal transform
                gdata[:, mg_slice, :, :] = 0
            else:
                # Use rectangular transform matrix, padded with zeros when Lmin > abs(m)
                grm = gdata[:, mg_slice, :, :]
                crm = cdata[:, mc_slice, ell_slice, :]
                apply_matrix(m_matrices[m], crm, axis=2, out=grm)

    @CachedAttribute
    def _quadrature(self):
        # get grid and weights from sphere library
        Lmax = self.N2g - 1
        return dedalus_sphere.sphere.quadrature(Lmax)

    @CachedAttribute
    def _forward_SWSH_matrices(self):
        """Build transform matrix for single m and s."""
        # Get functions from sphere library
        cos_grid, weights = self._quadrature
        Lmax = self.N2c - 1
        m_matrices = {}
        for m, _, _, _ in self.m_maps:
            if m in m_matrices:
                continue
            if m > Lmax:
                # Don't make matrices for m's that will be dropped after transform
                m_matrices[m] = None
            else:
                Y = dedalus_sphere.sphere.harmonics(Lmax, m, self.s, cos_grid)  # shape (Nc-Lmin, Ng)
                # Pad to shape (Nc-|m|, Ng) so transforms don't depend on Lmin
                Lmin = max(np.abs(m), np.abs(self.s))
                Yfull = np.zeros((self.N2c-np.abs(m), self.N2g))
                Yfull[Lmin-np.abs(m):, :] = (Y*weights).astype(np.float64)
                # Zero out modes higher than grid resolution
                Yfull[self.N2g:, :] = 0
                m_matrices[m] = np.asarray(Yfull, order='C')
        return m_matrices

    @CachedAttribute
    def _backward_SWSH_matrices(self):
        """Build transform matrix for single m and s."""
        # Get functions from sphere library
        cos_grid, weights = self._quadrature
        Lmax = self.N2c - 1
        m_matrices = {}
        for m, _, _, _ in self.m_maps:
            if m in m_matrices:
                continue
            if m > Lmax:
                # Don't make matrices for m's that will be dropped after transform
                m_matrices[m] = None
            else:
                Y = dedalus_sphere.sphere.harmonics(Lmax, m, self.s, cos_grid) # shape (Nc-Lmin, Ng)
                # Pad to shape (Nc-|m|, Ng) so transforms don't depend on Lmin
                Lmin = max(np.abs(m), np.abs(self.s))
                Yfull = np.zeros((self.N2g, self.N2c-np.abs(m)))
                Yfull[:, Lmin-np.abs(m):] = Y.T.astype(np.float64)
                # Zero out modes higher than grid resolution
                Yfull[:, self.N2g:] = 0
                m_matrices[m] = np.asarray(Yfull, order='C')
        return m_matrices

@register_transform(basis.DiskBasis, 'matrix')
class DiskRadialTransform(NonSeparableTransform):
    """
    TODO:
        - Remove dependence on grid_shape?
    """

    def __init__(self, grid_shape, basis_shape, axis, m_maps, s, k, alpha, dtype=np.complex128):
        self.Nphi = basis_shape[0]
        self.Nmax = basis_shape[1] - 1
        super().__init__(grid_shape, self.Nmax+1, axis, dtype)
        self.m_maps = m_maps
        self.s = s
        self.k = k
        self.alpha = alpha

    def forward_reduced(self, gdata, cdata):
        # local_m = self.local_m
        # if gdata.shape[1] != len(local_m): # do we want to do this check???
        #     raise ValueError("gdata.shape[1]: %i, len(local_m): %i" %(gdata.shape[1], len(local_m)))
        m_matrices = self._forward_matrices
        Nphi = self.Nphi
        Nmax = self.Nmax
        for m, mg_slice, mc_slice, n_slice in self.m_maps:
            # Skip transforms when |m| > 2*Nmax
            if np.abs(m) <= 2*Nmax:
                # Use rectangular transform matrix, padded with zeros when Nmin > abs(m)//2
                grm = gdata[:, mg_slice, :, :]
                crm = cdata[:, mc_slice, n_slice, :]
                apply_matrix(m_matrices[m], grm, axis=2, out=crm)

    def backward_reduced(self, cdata, gdata):
        # local_m = self.local_m
        # if gdata.shape[1] != len(local_m): # do we want to do this check???
        #     raise ValueError("gdata.shape[1]: %i, len(local_m): %i" %(gdata.shape[1], len(local_m)))
        m_matrices = self._backward_matrices
        Nphi = self.Nphi
        Nmax = self.Nmax
        for m, mg_slice, mc_slice, n_slice in self.m_maps:
            if np.abs(m) > 2*Nmax:
                # Write zeros because they'll be used by the inverse azimuthal transform
                gdata[:, mg_slice, :, :] = 0
            else:
                # Use rectangular transform matrix, padded with zeros when Nmin > abs(m)//2
                grm = gdata[:, mg_slice, :, :]
                crm = cdata[:, mc_slice, n_slice, :]
                apply_matrix(m_matrices[m], crm, axis=2, out=grm)

    @CachedAttribute
    def _quadrature(self):
        # get grid and weights from sphere library
        return dedalus_sphere.zernike.quadrature(2, self.N2g, k=self.alpha)

    @CachedAttribute
    def _forward_matrices(self):
        """Build transform matrix for single l and r."""
        # Get functions from sphere library
        z_grid, weights = self._quadrature
        m_list = tuple(map[0] for map in self.m_maps)
        m_matrices = {}
        for m in m_list:
            if m not in m_matrices:
                Nmin = dedalus_sphere.zernike.min_degree(m)
                Nc = self.N2c - Nmin
                W = dedalus_sphere.zernike.polynomials(2, Nc, self.k + self.alpha, np.abs(m + self.s), z_grid) # shape (N2c-Nmin, Ng)
                conversion = dedalus_sphere.zernike.operator(2, 'E')(+1)**self.k
                W = conversion(Nc, self.k + self.alpha, np.abs(m + self.s)) @ W
                W = (W*weights).astype(np.float64)
                # zero out modes higher than grid resolution taking into account n starts at Nmin
                W[self.N2g-Nmin:] = 0
                m_matrices[m] = np.asarray(W, order='C')
        return m_matrices

    @CachedAttribute
    def _backward_matrices(self):
        """Build transform matrix for single l and r."""
        # Get functions from sphere library
        z_grid, weights = self._quadrature
        m_list = tuple(map[0] for map in self.m_maps)
        m_matrices = {}

        for m in m_list:
            if m not in m_matrices:
                Nmin = dedalus_sphere.zernike.min_degree(m)
                Nc = self.N2c - Nmin
                W = dedalus_sphere.zernike.polynomials(2, Nc, self.k + self.alpha, np.abs(m + self.s), z_grid)
                m_matrices[m] = np.asarray(W.T.astype(np.float64), order='C')
        return m_matrices





@register_transform(basis.BallRadialBasis, 'matrix')
@register_transform(basis.BallBasis, 'matrix')
class BallRadialTransform(Transform):

    def __init__(self, grid_shape, coeff_size, axis, ell_maps, regindex, regtotal, k, alpha, dtype=np.complex128):

        self.N3g = grid_shape[axis]
        self.N3c = coeff_size

        self.ell_maps = ell_maps
        self.intertwiner = lambda l: dedalus_sphere.spin_operators.Intertwiner(l, indexing=(-1,+1,0))
        self.regindex = regindex
        self.regtotal = regtotal
        self.k = k
        self.alpha = alpha

    def forward(self, gdata, cdata, axis):
        # Make reduced view into input arrays
        gdata = reduced_view_5(gdata, axis-2)
        cdata = reduced_view_5(cdata, axis-2)
        # Transform reduced arrays
        self.forward_reduced(gdata, cdata)

    def backward(self, cdata, gdata, axis):
        # Make reduced view into input arrays
        cdata = reduced_view_5(cdata, axis-2)
        gdata = reduced_view_5(gdata, axis-2)
        # Transform reduced arrays
        self.backward_reduced(cdata, gdata)

    def forward_reduced(self, gdata, cdata):

        #if gdata.shape[1] != len(local_l): # do we want to do this check???
        #    raise ValueError("Local l must match size of %i axis." %(self.axis-1) )

        # Apply transform for each l
        ell_matrices = self._forward_GSZP_matrix
        for ell, m_ind, ell_ind in self.ell_maps:
            Nmin = dedalus_sphere.zernike.min_degree(ell)
            grl = gdata[:, m_ind, ell_ind, :, :]
            crl = cdata[:, m_ind, ell_ind, Nmin:, :]
            apply_matrix(ell_matrices[ell], grl, axis=3, out=crl)

    def backward_reduced(self, cdata, gdata):

        #if gdata.shape[1] != len(local_l): # do we want to do this check???
        #    raise ValueError("Local l must match size of %i axis." %(self.axis-1) )

        # Apply transform for each l
        ell_matrices = self._backward_GSZP_matrix
        for ell, m_ind, ell_ind in self.ell_maps:
            Nmin = dedalus_sphere.zernike.min_degree(ell)
            grl = gdata[:, m_ind, ell_ind, :, :]
            crl = cdata[:, m_ind, ell_ind, Nmin:, :]
            apply_matrix(ell_matrices[ell], crl, axis=3, out=grl)

    @CachedAttribute
    def _quadrature(self):
        # get grid and weights from sphere library
        return dedalus_sphere.zernike.quadrature(3, self.N3g, k=self.alpha)

    @CachedAttribute
    def _forward_GSZP_matrix(self):
        """Build transform matrix for single l and r."""
        # Get functions from sphere library
        z_grid, weights = self._quadrature
        ell_list = tuple(map[0] for map in self.ell_maps)
        ell_matrices = {}
        Rb = np.array([-1, 1, 0], dtype=int)
        for ell in ell_list:
            if ell not in ell_matrices:
                if self.regindex != () and self.intertwiner(ell).forbidden_regularity(Rb[np.array(self.regindex)]):
                    ell_matrices[ell] = np.zeros((self.N3c, self.N3g))
                else:
                    Nmin = dedalus_sphere.zernike.min_degree(ell)
                    Nc = self.N3c - Nmin
                    W = dedalus_sphere.zernike.polynomials(3, Nc, self.alpha, ell + self.regtotal, z_grid) # shape (N3c-Nmin, Ng)
                    conversion = dedalus_sphere.zernike.operator(3, 'E')(+1)**self.k
                    W = conversion(Nc, self.alpha, ell + self.regtotal) @ W
                    W = (W*weights).astype(np.float64)
                    # zero out modes higher than grid resolution taking into account n starts at Nmin
                    W[self.N3g-Nmin:] = 0
                    ell_matrices[ell] = np.asarray(W, order='C')
        return ell_matrices

    @CachedAttribute
    def _backward_GSZP_matrix(self):
        """Build transform matrix for single l and r."""
        # Get functions from sphere library
        z_grid, weights = self._quadrature
        ell_list = tuple(map[0] for map in self.ell_maps)
        ell_matrices = {}
        Rb = np.array([-1, 1, 0], dtype=int)
        for ell in ell_list:
            if ell not in ell_matrices:
                if self.regindex != () and self.intertwiner(ell).forbidden_regularity(Rb[np.array(self.regindex)]):
                    ell_matrices[ell] = np.zeros((self.N3g, self.N3c))
                else:
                    Nmin = dedalus_sphere.zernike.min_degree(ell)
                    Nc = self.N3c - Nmin
                    W = dedalus_sphere.zernike.polynomials(3, Nc, self.alpha + self.k, ell + self.regtotal, z_grid)
                    ell_matrices[ell] = np.asarray(W.T.astype(np.float64), order='C')
        return ell_matrices


## Disk transforms

def forward_disk(gdata, cdata, axis, k0, k, s, local_m):
    """Apply forward radial transform to data with fixed s and varying m."""
    # Build reduced views
    gdata_reduced = reduced_view_4(gdata, axis-1)
    cdata_reduced = reduced_view_4(cdata, axis-1)
    if gdata_reduced.shape[1] != len(local_m):
        raise ValueError("Local m must match axis-1 size.")
    # Apply transform for each m
    Ng = gdata.shape[axis]
    Nc = cdata.shape[axis]
    for dm, m in enumerate(local_m):
        m_matrix = _forward_disk_matrix(Ng, Nc, k0, k, m+s)
        grm = gdata_reduced[:, dm, :, :]
        crm = cdata_reduced[:, dm, :, :]
        apply_matrix(m_matrix, grm, axis=1, out=crm)

def _forward_disk_matrix(Ng, Nc, k0, k, m):
    """Build forward transform matrix for Q[k,m,n](r[k0])."""
    # Get base grid and weights
    z_grid, weights = dedalus_sphere.disk128.quadrature(Ng-1, k=k0, niter=3)
    # Get functions
    Nc_max = Nc
    logger.warn("No truncation")
    Q = dedalus_sphere.disk128.polynomials(Nc_max-1, k=k, m=m, z=z_grid)
    # Pad to square transform
    Qfull = np.zeros((Nc, Ng))
    Qfull[:Nc, :] = Q.astype(np.float64)
    return Qfull

def backward_disk(cdata, gdata, axis, k, s, local_m):
    """Apply bakward radial transform to data with fixed s and varying m."""
    # Build reduced views
    gdata_reduced = reduced_view_4(gdata, axis-1)
    cdata_reduced = reduced_view_4(cdata, axis-1)
    if gdata_reduced.shape[1] != len(local_m):
        raise ValueError("Local m must match axis-1 size.")
    # Apply transform for each m
    for dm, m in enumerate(local_m):
        m_matrix = _backward_SWSH_matrix(N2c, N2g, k, m+s)
        grm = gdata_reduced[:, dm, :, :]
        crm = cdata_reduced[:, dm, :, :]
        apply_matrix(m_matrix, crm, axis=1, out=grm)

def _backward_disk_matrix(Nc, Ng, k0, k, m):
    """Build backward transform matrix for Q[k,m,n](r[k0])."""
    # Get base grid and weights
    z_grid, weights = dedalus_sphere.disk128.quadrature(Ng-1, k=k0, niter=3)
    # Get functions
    Nc_max = Nc
    logger.warn("No truncation")
    Q = dedalus_sphere.disk128.polynomials(Nc_max-1, k=k, m=m, z=z_grid)
    # Pad to square transform
    Qfull = np.zeros((Nc, Ng))
    Qfull[:Nc, :] = Q.astype(np.float64)
    return Qfull

