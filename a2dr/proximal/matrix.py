import numpy as np
import numpy.linalg as LA
from a2dr.proximal.composition import prox_scale
from a2dr.proximal.projection import proj_simplex

def prox_neg_log_det(B, t = 1, *args, **kwargs):
    """Proximal operator of :math:`tf(aB-b) + cB + d\\|B\\|_F^2`, where :math:`f(B) = -\\log\\det(B)`
    for scalar t > 0, and the optional arguments are a = scale, b = offset, c = lin_term, and d = quad_term.
    We must have t > 0, a = non-zero, and d > 0. By default, t = 1, a = 1, b = 0, c = 0, and d = 0.
    """
    return prox_scale(prox_neg_log_det_base, *args, **kwargs)(B, t)

def prox_sigma_max(B, t = 1, *args, **kwargs):
    """Proximal operator of :math:`tf(aB-b) + cB + d\\|B\\|_F^2`, where :math:`f(B) = \\sigma_{\\max}(B)`
    is the maximum singular value of :math:`B`, for scalar t > 0, and the optional arguments are a = scale,
    b = offset, c = lin_term, and d = quad_term. We must have t > 0, a = non-zero, and d > 0. By default,
    t = 1, a = 1, b = 0, c = 0, and d = 0.
    """
    return prox_scale(prox_sigma_max_base, *args, **kwargs)(B, t)

def prox_trace(B, t = 1, *args, **kwargs):
    """Proximal operator of :math:`tf(aB-b) + cB + d\\|B\\|_F^2`, where :math:`f(B) = tr(B)` is the trace of
    :math:`B`, for scalar t > 0, and the optional arguments are a = scale, b = offset, c = lin_term, and
    d = quad_term. We must have t > 0, a = non-zero, and d > 0. By default, t = 1, a = 1, b = 0, c = 0, and
    d = 0.
    """
    return prox_scale(prox_trace_base, *args, **kwargs)(B, t)

def prox_neg_log_det_base(B, t):
	"""Proximal operator of :math:`f(B) = -\\log\\det(B)`.
	"""
	B_symm = (B + B.T) / 2.0
	if not (np.allclose(B, B_symm)):
		raise Exception("Proximal operator for negative log-determinant only operates on symmetric matrices.")
	s, u = LA.eigh(B_symm)
	id_pos = (s >= 0)
	id_neg = (s < 0)
	s_new = np.zeros(len(s))
	s_new[id_pos] = (s[id_pos] + np.sqrt(s[id_pos]**2 + 4.0*t))/2
	s_new[id_neg] = 2.0*t/(np.sqrt(s[id_neg]**2 + 4.0*t) - s[id_neg])
	return u.dot(np.diag(s_new)).dot(u.T)

def prox_sigma_max_base(B, t):
	"""Proximal operator of :math:`f(B) = \\sigma_{\\max}(B)`, the maximum singular value of :math:`B`.
	"""
	U, s, Vt = LA.svd(B, full_matrices=False)
	s_new = t * proj_simplex(s/t)
	return U.dot(np.diag(s_new)).dot(Vt)

def prox_trace_base(B, t):
	"""Proximal operator of :math:`f(B) = tr(B)`, the trace of :math:`B`.
	"""
	return B - np.diag(np.full((B.shape[0],), t))
