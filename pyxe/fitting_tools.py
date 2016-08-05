# -*- coding: utf-8 -*-
"""
Created on Wed Jul 15 08:34:51 2015

@author: Chris
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import sys
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit
from numpy.polynomial.chebyshev import chebval
import numba

from pyxe.fitting_functions import gaussian, lorentzian, psuedo_voigt, strain_transformation


@numba.jit(nopython=True)
def sum_numba(a):
    return np.sum(a, axis=0)

@numba.jit(nopython=True)
def pawley_sum(I, h, q, q0, fwhm):
    sig = fwhm / (2 * np.sqrt(2 * np.log(2)))
    for i in range(len(q0)):
        I = I + h[i] * np.exp(-(q - q0[i]) ** 2 / (2 * sig[i] ** 2))
    return I


def pawley_hkl(detector, back):
    """Pawley wrapper allows you to pass in a detector. """
    def pawley(q, *p):

        p0 = len(detector.hkl) + 3
        I = np.zeros_like(q)
        p_fw = p[p0 - 3: p0]

        # if detector.method == 'energy':
        #     fwhm_q = lambda q: np.polyval(p_fw, q) ** 0.5
        # else:
        #     fwhm_q = lambda q: np.tan

        for idx, material in enumerate(detector.materials):
            # Extract number of peaks and associated hkl values
            npeaks = len(detector.hkl[material])
            hkl = [[int(col) for col in row] for row in detector.hkl[material]]

            # Estimate of a and associated q0/d0 values
            a = p[idx]
            d0 = a / np.sqrt(np.sum(np.array(hkl)**2, axis=1))
            q0 = 2 * np.pi / d0
            q0 = q0[np.logical_and(q0>np.min(q), q0<np.max(q))]

            # Calculate FWHM and (associated) sigma/c value
            fwhm = np.expand_dims(detector.fwhm_q(q0, p_fw), 1)

            # Extract intensity values
            h = np.array(p[p0: p0 + npeaks])

            I = pawley_sum(I, h, q, q0, fwhm)
            p0 += npeaks

        return I + back
    return pawley

def pawley_hkl_old(detector, back):
    """Pawley wrapper allows you to pass in a detector. """


    def pawley(q, *p):

        p0 = len(detector.hkl) + 2
        I = np.zeros_like(q)
        p_fw = p[p0 - 2: p0]
        # back = 2# p[-1] * chebval(q, detector.background)

        for idx, material in enumerate(detector.materials):
            # Extract number of peaks and associated hkl values
            npeaks = len(detector.hkl[material])
            hkl = [[int(col) for col in row] for row in detector.hkl[material]]

            # Estimate of a and associated q0/d0 values
            a = p[idx]
            d0 = a / np.sqrt(np.sum(np.array(hkl)**2, axis=1))
            q0 = 2 * np.pi / d0
            q0 = q0[np.logical_and(q0>np.min(q), q0<np.max(q))]

            # Calculate FWHM and (associated) sigma/c value
            fwhm = detector.fwhm_q(np.expand_dims(detector.sigma_q(q0), 1), p_fw)
            # fwhm = p_fw[1] + p_fw[0] * np.expand_dims(detector.sigma_q(q0), 1)
            sig = fwhm / (2 * np.sqrt(2 * np.log(2)))

            # Extract intensity values
            p_int = p[p0: p0 + npeaks]
            h = np.expand_dims(p_int, axis=1)

            q_cent = q - np.expand_dims(q0, axis=1)

            # print(q_cent.shape, back.shape, h.shape, sig.shape)
            I += np.sum(h * np.exp(-q_cent**2 / (2 * sig**2)), axis=0)
            p0 += npeaks

        return I + back
    return pawley


def extract_parameters(detector, q_lim, I_max=1):
    p = [detector.materials[mat]['a'] for mat in detector.materials]
    p += detector._fwhm
    for idx, material in enumerate(detector.materials):
        for idx, i in enumerate(detector.relative_heights()[material]):
            q0 = detector.q0[material][idx]
            if np.logical_and(q0 > q_lim[0], q0 < q_lim[1]):
                p.append(i * I_max)

    return p


def array_fit_pawley(q_array, I_array, detector, err_lim=1e-4,
                     q_lim=[2, None], progress=True):
    # data = (np.zeros(I_array.shape[:-1]) * np.nan, ) * 4
    data = [np.nan * np.ones(I_array.shape[:-1]) for _ in range(4)]
    peaks, peaks_err, fwhm, fwhm_err = data
    slices = [i for i in range(q_array.shape[0])]

    err_exceed, run_error = 0, 0



    for az_idx in slices:

        # Load in detector calibrated q array and crop data
        q = q_array[az_idx]
        q_lim[0] = q_lim[0] if q_lim[0] is not None else np.min(q)
        q_lim[1] = q_lim[1] if q_lim[1] is not None else np.max(q)
        crop = np.logical_and(q > q_lim[0], q < q_lim[1])
        q = q[crop]

        if detector._back.ndim == 2:
            background = chebval(q, detector._back[az_idx])

        else:
            background = chebval(q, detector._back)


        for position in np.ndindex(I_array.shape[:-2]):
            index = position + (az_idx,)
            I = I_array[index][crop]
            p0 = extract_parameters(detector, q_lim, np.nanmax(I))

            # Fit peak across window
            try:
                # background = chebval(q, detector.background[az_idx])
                pawley = pawley_hkl(detector, background)
                coeff, var_mat = curve_fit(pawley, q, I, p0=p0)
                perr = np.sqrt(np.diag(var_mat))
                peak, peak_err = coeff[0], perr[0]
                # Check error and store
                if peak_err / peak > err_lim:
                    err_exceed += 1
                else:
                    peaks[index], peaks_err[index] = peak, peak_err
            except RuntimeError:
                run_error += 1

            if progress:
                frac = (az_idx + 1) / len(slices)
                prog = '\rProgress: [{0:20s}] {1:.0f}%'
                sys.stdout.write(prog.format('#' * int(20 * frac), 100 * frac))
                sys.stdout.flush()

    print('\nTotal points: %i (%i az_angles x %i positions)'
          '\nPeak not found in %i position/detector combinations'
          '\nError limit exceeded (or pcov not estimated) %i times' %
          (peaks.size, peaks.shape[-1], peaks[..., 0].size,
           run_error, err_exceed))

    return peaks, peaks_err, None, None



def p0_approx(data, peak_window, func='gaussian'):
    """
    Approximates p0 for curve fitting.
    Now estimates stdev.
    """
    x, y = data

    if x[0] > x[1]:
        x = x[::-1]
        y = y[::-1]

    peak_ind = np.searchsorted(x, peak_window)
    x_ = x[peak_ind[0]:peak_ind[1]]
    I_ = y[peak_ind[0]:peak_ind[1]]
    max_index = np.argmax(I_)
    hm = min(I_) + (max(I_) - min(I_)) / 2
    
    stdev = x_[max_index + np.argmin(I_[max_index:] > hm)] - x_[max_index]
    if stdev <= 0:
        stdev = 0.1
    p0 = [min(I_), max(I_) - min(I_), x_[max_index], stdev]

    if func == 'psuedo_voigt':
        p0.append(0.5)
    return p0


def peak_fit(data, window, p0=None, func='gaussian'):
    """
    Takes a function (guassian/lorentzian) and information about the peak 
    and calculates the peak location and standard deviation. 
    """
    func_dict = {'gaussian': gaussian, 'lorentzian': lorentzian, 
                 'psuedo_voigt': psuedo_voigt}
    func_name = func
    func = func_dict[func.lower()]
    
    if data[0][0] > data[0][-1]:
        data[0] = data[0][::-1]
        data[1] = data[1][::-1]
        
    if p0 is None:
        p0 = p0_approx(data, window, func_name)
        
    peak_ind = np.searchsorted(data[0], window)
    x_ = data[0][peak_ind[0]:peak_ind[1]]
    I_ = data[1][peak_ind[0]:peak_ind[1]]

    return curve_fit(func, x_, I_, p0)


def array_fit(q_array, I_array, peak_window, func='gaussian', 
              error_limit=10 ** -4, progress=True):
        
    # data = (np.zeros(I_array.shape[:-1]) * np.nan, ) * 4
    data = [np.nan * np.ones(I_array.shape[:-1]) for i in range(4)]
    peaks, peaks_err, fwhm, fwhm_err = data 
    slices = [i for i in range(q_array.shape[0])]

    err_exceed, run_error = 0, 0

    for idx, detector in enumerate(slices):

        # Load in detector calibrated q array
        q = q_array[detector]
        for position in np.ndindex(I_array.shape[:-2]):
            index = position + (detector,)
            I = I_array[index]
            p0 = p0_approx((q, I), peak_window, func)
            # Fit peak across window
            try:
                coeff, var_matrix = peak_fit((q, I), peak_window, p0, func)
                perr = np.sqrt(np.diag(var_matrix))                
                peak, peak_err = coeff[2], perr[2]
                fw, fw_err = coeff[3], perr[3]
                if func == 'gaussian':
                    fw, fw_err = fw * 2.35482, fw_err * 2.35482
                elif func == 'lorentzian':
                    fwhm, fwhm_err = fw * 2, fw_err * 2
                # Check error and store
                if peak_err / peak > error_limit:
                    err_exceed += 1
                else:
                    peaks[index], peaks_err[index] = peak, peak_err
                    fwhm[index], fwhm_err[index] = fw, fw_err
            except RuntimeError:
                run_error += 1
                
            if progress:
                sys.stdout.write('\rProgress: [{0:20s}] {1:.0f}%'.format('#' *
                                 int(20*(idx + 1)/len(slices)),
                                 100*((idx + 1)/len(slices))))
                sys.stdout.flush()
                  
    print('\nTotal points: %i (%i az_angles x %i positions)'
          '\nPeak not found in %i position/detector combintions'
          '\nError limit exceeded (or pcov not estimated) %i times' % 
          (peaks.size, peaks.shape[-1], peaks[..., 0].size, 
           run_error, err_exceed))                  
    
    return peaks, peaks_err, fwhm, fwhm_err


def full_ring_fit(strain, phi):
    """
    Fits the strain transformation equation to the strain information from each
    azimuthal slice.
    """
    strain_tensor = np.nan * np.ones(strain.shape[:-1] + (3,))

    error_count = 0
    for idx in np.ndindex(strain.shape[:-1]):
        data = strain[idx]
        not_nan = ~np.isnan(data)

        phi_range = np.max(phi) - np.min(phi)
        # nyquist - twice the frequency response (strain freq = 2 * ang freq)
        nyquist_sampling = 1 + 2 * np.ceil(2 * phi_range / np.pi)
        if phi[not_nan].size >= nyquist_sampling:
            # Estimate curve parameters
            p0 = [np.nanmean(data), 3 * np.nanstd(data) / (2 ** 0.5), 0]
            try:
                a, b = curve_fit(strain_transformation,
                                 phi[not_nan], data[not_nan], p0)
                strain_tensor[idx] = a
            except (TypeError, RuntimeError):
                error_count += 1
        else:
            error_count += 1
    print('\nUnable to fit full ring at %i out of %i points'
          % (error_count, np.size(strain[..., 0])))

    return strain_tensor


def mirror_data(phi, data):
    # has to be even number of slices but uneven number of boundaries.
    angles = phi[:int(phi[:].shape[0]/2)]
    peak_shape = data.shape
    phi_len = int(peak_shape[-2]/2)
    new_shape = (peak_shape[:-2] + (phi_len, ) + peak_shape[-1:])
    d2 = np.nan * np.zeros(new_shape)
    for i in range(phi_len):
        d2[:, i] = (data[:, i] + data[:, i + new_shape[-2]]) / 2
    return angles, d2



if __name__ == '__main__':
    import os
    from pyxe.energy_dispersive import EDI12
    base = os.path.split(os.path.dirname(__file__))[0]
    fpath_1 = os.path.join(base, r'pyxe/data/50418.nxs')
    fpath_2 = os.path.join(base, r'pyxe/data/50414.nxs')
    fine = EDI12(fpath_1)
    fine.add_material('Fe')
    fine.plot_intensity(pawley=True)
    plt.show()
    print(fine.detector.fwhm_param)