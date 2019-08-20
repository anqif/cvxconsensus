"""
Copyright 2018 Anqi Fu

This file is part of A2DR.

A2DR is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

A2DR is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with A2DR. If not, see <http://www.gnu.org/licenses/>.
"""
import numpy as np
from time import time
from multiprocessing import Process, Pipe
from a2dr.prox_point import prox_point
from a2dr.precondition import precondition
from a2dr.acceleration import aa_weights

def a2dr_worker(pipe, prox, v_init, A, rho, anderson, m_accel):
    # Initialize AA-II parameters.
    if anderson:   # TODO: Store and update these efficiently as arrays.
        F_hist = []  # History of F(v^(k)).
    v_vec = v_init.copy()
    v_res = np.zeros(v_init.shape[0])

    # A2DR loop.
    while True:
        # Proximal step for x^(k+1/2).
        x_half = prox(v_vec, rho)

        # Calculate v^(k+1/2) = 2*x^(k+1/2) - v^(k).
        v_half = 2*x_half - v_vec

        # Project to obtain x^(k+1) = v^(k+1/2) - A^T(AA^T)^{-1}(Av^(k+1/2) - b).
        pipe.send(v_half)
        d_half, k = pipe.recv()   # d_half = (AA^T)^{-1}(Av^(k+1/2) - b).
        x_new = v_half - A.T.dot(d_half)

        if anderson:
            m_k = min(m_accel, k+1)  # Keep F(v^(j)) for iterations (k-m_k) through k.

            # Save history of F(v^(k)).
            F_hist.append(v_vec + x_new - x_half)
            if len(F_hist) > m_k + 1:
                F_hist.pop(0)

            # Send s^(k-1) = v^(k) - v^(k-1) and g^(k) = v^(k) - F(v^(k)) = x^(k+1/2) - x^(k+1).
            pipe.send((v_res, x_half - x_new))

            # Receive AA-II weights for v^(k+1).
            alpha = pipe.recv()

            # Weighted update of v^(k+1).
            v_new = np.column_stack(F_hist).dot(alpha[:(k+1)])

            # Save v^(k+1) - v^(k) for next iteration.
            v_res = v_new - v_vec
        else:
            # Update v^(k+1) = v^(k) + x^(k+1) - x^(k+1/2).
            v_new = v_vec + x_new - x_half

        # Send A*x^(k+1/2) and x^(k+1/2) - v^(k) for computing residuals.
        pipe.send((A.dot(x_half), x_half - v_vec))
        v_vec = v_new

        # Send x_i^(k+1/2) if A2DR terminated.
        finished = pipe.recv()
        if finished:
            pipe.send(x_half)

# TODO: Warm start lstsq. Implement sparse handling.
def a2dr(p_list, v_init, A_list = [], b = np.array([]), *args, **kwargs):
    # Problem parameters.
    max_iter = kwargs.pop("max_iter", 1000)
    rho_init = kwargs.pop("rho_init", 1.0)  # Step size.
    eps_abs = kwargs.pop("eps_abs", 1e-6)   # Absolute stopping tolerance.
    eps_rel = kwargs.pop("eps_rel", 1e-8)   # Relative stopping tolerance.
    precond = kwargs.pop("precond", False)  # Precondition A and b?

    # AA-II parameters.
    anderson = kwargs.pop("anderson", False)
    m_accel = int(kwargs.pop("m_accel", 5))  # Maximum past iterations to keep (>= 0).
    lam_accel = kwargs.pop("lam_accel", 0)   # AA-II regularization weight.

    # Validate parameters.
    if max_iter <= 0:
        raise ValueError("max_iter must be a positive integer.")
    if rho_init <= 0:
        raise ValueError("rho_init must be a positive scalar.")
    if eps_abs < 0:
        raise ValueError("eps_abs must be a non-negative scalar.")
    if eps_rel < 0:
        raise ValueError("eps_rel must be a non-negative scalar.")
    if m_accel <= 0:
        raise ValueError("m_accel must be a positive integer.")
    if lam_accel < 0:
        raise ValueError("lam_accel must be a non-negative scalar.")

    # DRS parameters.
    N = len(p_list)   # Number of subproblems.
    if len(v_init) != N:
        raise ValueError("p_list and v_init must contain the same number of entries")
    if len(A_list) == 0:
        return prox_point(p_list, v_init, *args, **kwargs)
    if len(A_list) != N:
        raise ValueError("A_list must be empty or contain exactly {} entries".format(N))
    for i in range(N):
        if A_list[i].shape[0] != b.shape[0]:
            raise ValueError("Dimension mismatch: nrow(A_i) != nrow(b)")
        elif A_list[i].shape[1] != v_init[i].shape[0]:
            raise ValueError("Dimension mismatch: ncol(A_i) != nrow(v_i)")

    # Precondition data.
    if precond:
        p_list, A_list, b, e_pre = precondition(p_list, A_list, b, tol = eps_abs, max_iter = max_iter)
    A = np.hstack(A_list)
    AAT = A.dot(A.T)   # Store for projection step.

    # Set up the workers.
    pipes = []
    procs = []
    for i in range(N):
        local, remote = Pipe()
        pipes += [local]
        procs += [Process(target=a2dr_worker, args=(remote, p_list[i], v_init[i], A_list[i], \
                                                    rho_init, anderson, m_accel) + args)]
        procs[-1].start()

    # Initialize AA-II variables.
    if anderson:   # TODO: Store and update these efficiently as arrays.
        n_sum = np.sum([v.size for v in v_init])
        g_vec = np.zeros(n_sum)   # g^(k) = v^(k) - F(v^(k)).
        s_hist = []  # History of s^(j) = v^(j+1) - v^(j), kept in S^(k) = [s^(k-m_k) ... s^(k-1)].
        y_hist = []  # History of y^(j) = g^(j+1) - g^(j), kept in Y^(k) = [y^(k-m_k) ... y^(k-1)].

    # A2DR loop.
    k = 0
    finished = False
    r_primal = np.zeros(max_iter)
    r_dual = np.zeros(max_iter)

    start = time()
    while not finished:
        # Gather v_i^(k+1/2) from nodes.
        v_halves = [pipe.recv() for pipe in pipes]

        # Projection step for x^(k+1).
        v_half = np.concatenate(v_halves, axis=0)
        d_half = np.linalg.lstsq(AAT, A.dot(v_half) - b, rcond=None)[0]

        # Scatter d^(k+1/2) = (AA^T)^{-1}(Av^(k+1/2) - b).
        for pipe in pipes:
            pipe.send((d_half, k))

        if anderson:
            m_k = min(m_accel, k+1)  # Keep (y^(j), s^(j)) for iterations (k-m_k) through (k-1).

            # Gather s_i^(k-1) and g_i^(k) from nodes.
            sg_update = [pipe.recv() for pipe in pipes]
            s_new, g_new = map(list, zip(*sg_update))
            s_new = np.concatenate(s_new, axis=0)   # s_i^(k-1) = v_i^(k) - v_i^(k-1).
            g_new = np.concatenate(g_new, axis=0)   # g_i^(k) = v_i^(k) - F(v_i^(k)) = x_i^(k+1/2) - x_i^(k+1).

            # Save newest column y^(k-1) = g^(k) - g^(k-1) of matrix Y^(k).
            y_hist.append(g_new - g_vec)
            if len(y_hist) > m_k:
                y_hist.pop(0)
            g_vec = g_new

            # Save newest column s^(k-1) = v^(k) - v^(k-1) of matrix S^(k).
            s_hist.append(s_new)
            if len(s_hist) > m_k:
                s_hist.pop(0)

            # Compute and scatter AA-II weights.
            Y_mat = np.column_stack(y_hist)
            S_mat = np.column_stack(s_hist)
            reg = lam_accel*(np.linalg.norm(Y_mat)**2 + np.linalg.norm(S_mat)**2)   # AA-II regularization.
            alpha = aa_weights(Y_mat, g_new, reg, rcond=None)
            for pipe in pipes:
                pipe.send(alpha)

        # Compute l2-norm of primal and dual residuals.
        r_update = [pipe.recv() for pipe in pipes]
        Ax_halves, xv_diffs = map(list, zip(*r_update))
        r_primal[k] = np.linalg.norm(sum(Ax_halves) - b, ord=2)
        subgrad = rho_init*np.concatenate(xv_diffs)
        sol = np.linalg.lstsq(A.T, subgrad, rcond=None)[0]
        r_dual[k] = np.linalg.norm(A.T.dot(sol) - subgrad, ord=2)

        # Stop if residual norms fall below tolerance.
        k = k + 1
        finished = k >= max_iter or (r_primal[k-1] <= eps_abs + eps_rel * r_primal[0] and \
                                     r_dual[k-1] <= eps_abs + eps_rel * r_dual[0])
        for pipe in pipes:
            pipe.send(finished)

    # Gather and return x_i^(k+1/2) from nodes.
    x_final = [pipe.recv() for pipe in pipes]
    [p.terminate() for p in procs]
    if precond:
        x_final = [ei*x for x, ei in zip(x_final, e_pre)]
    end = time()
    return {"x_vals": x_final, "primal": np.array(r_primal[:k]), "dual": np.array(r_dual[:k]), \
            "num_iters": k, "solve_time": (end - start)}