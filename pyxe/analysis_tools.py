# -*- coding: utf-8 -*-
"""
Created on Tue Oct 20 17:40:07 2015

@author: casimp
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from six import string_types, binary_type
import h5py
import numpy as np
from scipy.optimize import curve_fit
from pyxe.fitting_functions import strain_transformation


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


def pyxe_to_hdf5(fname, pyxe_object, overwrite=False):
    """
    Saves all data back into an expanded .nxs file. Contains all original
    data plus q0, peak locations and strain.

    # fname:      File name/location - default is to save to parent
                  directory (*_pyxe.nxs)
    """
    data_ids = ['ndim', 'd1', 'd2', 'd3', 'q', 'I', 'phi',
                'peaks', 'peaks_err', 'fwhm', 'fwhm_err',
                'strain', 'strain_err', 'strain_tensor',
                'E', 'v', 'G', 'stress_state', 'analysis_state']

    write = 'w' if overwrite else 'w-'
    with h5py.File(fname, write) as f:

        for name in data_ids:
            d_path = 'pyxe_analysis/%s' % name
            data = getattr(pyxe_object, name)
            data = data.encode() if isinstance(data, string_types) else data
            if data is not None:
                if name == 'I':
                    f.create_dataset(d_path, data=data, compression='gzip')
                else:
                    f.create_dataset(d_path, data=data)


def data_extract(pyxe_h5, data_id):

    data_ids = {'dims': ['ndim', 'd1', 'd2', 'd3'],
                'raw': ['q', 'I', 'phi'],
                'peaks': ['peaks', 'peaks_err'],
                'fwhm': ['fwhm', 'fwhm_err'],
                'strain': ['strain', 'strain_err'],
                'tensor': ['strain_tensor'],
                'material': ['E', 'v', 'G'],
                'state': ['stress_state', 'analysis_state']}

    extract = data_ids[data_id]
    data = []
    for ext in extract:
        try:
            d = pyxe_h5['pyxe_analysis/{}'.format(ext)]
            d = d[()].decode() if isinstance(d[()], binary_type) else d[()]
            data.append(d)
        except KeyError:
            data.append(None)
    return data


def dim_fill(data):

    co_ords = []
    dims = []
    
    if data.ndim == 1:
        return [data, None, None], [b'ss2_x']
    for axis, dim in zip(range(3), [b'ss2_x', b'ss2_y', b'ss2_z']):
        try:
            co_ords.append(data[:, axis])
            dims.append(dim)
        except IndexError:
            co_ords.append(None)
    return co_ords, dims


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


def dimension_fill(data, dim_id):
    """
    Extracts correct spatial array from hdf5 file. Returns None is the
    dimension doesn't exist.

    # data:       Raw data (hdf5 format)
    # dim_ID:     Dimension ID (ss_x, ss2_y or ss2_z)
    """
    try:
        dimension_data = data['entry1/EDXD_elements/' + dim_id][()]
    except KeyError:
        dimension_data = None
    return dimension_data
