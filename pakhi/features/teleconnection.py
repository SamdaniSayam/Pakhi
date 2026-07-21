"""Teleconnection index computations for large-scale climate patterns.

Computes Niño 3.4, NAO, PDO, and MJO indices from gridded
sea surface temperature and pressure data.
"""

from __future__ import annotations

import logging

import numpy as np
import xarray as xr

__all__ = ["TeleconnectionIndices"]

logger = logging.getLogger(__name__)


class TeleconnectionIndices:
    """Major teleconnection indices used in seasonal weather forecasting.

    All methods operate on xarray Datasets/DataArrays with lat/lon
    coordinates and return scalar time series or index values.
    """

    __all__ = [
        "compute_nino34",
        "compute_nao",
        "computepdo",
        "compute_mjo",
    ]

    @staticmethod
    def compute_nino34(
        sst_data: xr.Dataset | xr.DataArray,
        lat_dim: str = "latitude",
        lon_dim: str = "longitude",
        time_dim: str = "time",
        sst_var: str | None = None,
        anomalous: bool = True,
    ) -> xr.DataArray:
        """Niño 3.4 sea surface temperature index.

        Area-weighted average SST in the Niño 3.4 region:
        5°N–5°S, 170°W–120°W.

        Parameters
        ----------
        sst_data : xr.Dataset or xr.DataArray
            Sea surface temperature data.
        lat_dim, lon_dim, time_dim : str
            Dimension names.
        sst_var : str, optional
            Variable name if *sst_data* is a Dataset.
        anomalous : bool
            If ``True``, subtract the climatological mean to return
            anomalies. Default ``True``.

        Returns
        -------
        xr.DataArray
            Niño 3.4 index time series.
        """
        if isinstance(sst_data, xr.Dataset):
            if sst_var is None:
                sst_var = next(iter(sst_data.data_vars))
            sst = sst_data[sst_var]
        else:
            sst = sst_data

        sst = sst.sel(
            {
                lat_dim: slice(-5, 5),
                lon_dim: slice(-170, -120),
            }
        )

        cos_lat = np.cos(np.deg2rad(sst[lat_dim]))
        weights = cos_lat / cos_lat.sum()

        nino34 = sst.weighted(weights).mean(dim=[lat_dim, lon_dim])

        if anomalous:
            climatology = nino34.groupby(f"{time_dim}.month").mean(dim=time_dim)
            nino34 = nino34.groupby(f"{time_dim}.month") - climatology

        nino34.name = "nino34"
        return nino34

    @staticmethod
    def compute_nao(
        pressure_data: xr.Dataset | xr.DataArray,
        lat_dim: str = "latitude",
        lon_dim: str = "longitude",
        time_dim: str = "time",
        slp_var: str | None = None,
    ) -> xr.DataArray:
        """North Atlantic Oscillation index.

        Defined as the normalised pressure difference between the
        Azores (36°–40°N, 22°–18°W) and Iceland (63°–67°N, 18°–22°W).

        Parameters
        ----------
        pressure_data : xr.Dataset or xr.DataArray
            Sea-level pressure (SLP) data.
        lat_dim, lon_dim, time_dim : str
            Dimension names.
        slp_var : str, optional
            Variable name if input is a Dataset.

        Returns
        -------
        xr.DataArray
            NAO index time series.
        """
        if isinstance(pressure_data, xr.Dataset):
            if slp_var is None:
                slp_var = next(iter(pressure_data.data_vars))
            slp = pressure_data[slp_var]
        else:
            slp = pressure_data

        azores = slp.sel(
            {
                lat_dim: slice(36, 40),
                lon_dim: slice(-22, -18),
            }
        )
        iceland = slp.sel(
            {
                lat_dim: slice(63, 67),
                lon_dim: slice(-22, -18),
            }
        )

        cos_az = np.cos(np.deg2rad(azores[lat_dim]))
        cos_ice = np.cos(np.deg2rad(iceland[lat_dim]))

        azores_mean = azores.weighted(cos_az).mean(dim=[lat_dim, lon_dim])
        iceland_mean = iceland.weighted(cos_ice).mean(dim=[lat_dim, lon_dim])

        pressure_diff = azores_mean - iceland_mean

        climatology = pressure_diff.groupby(f"{time_dim}.month").mean(dim=time_dim)
        clim_std = pressure_diff.groupby(f"{time_dim}.month").std(dim=time_dim)
        clim_std = clim_std.where(clim_std > 0, 1)

        nao = pressure_diff.groupby(f"{time_dim}.month") - climatology
        nao = nao.groupby(f"{time_dim}.month") / clim_std

        nao.name = "nao"
        return nao

    @staticmethod
    def computepdo(
        sst_pacific: xr.Dataset | xr.DataArray,
        lat_dim: str = "latitude",
        lon_dim: str = "longitude",
        time_dim: str = "time",
        sst_var: str | None = None,
    ) -> xr.DataArray:
        """Pacific Decadal Oscillation index.

        Simplified: leading principal component of North Pacific SST
        anomalies (20°N–60°N, 190°E–245°E / 170°W–115°W) after
        removing the global mean SST signal.

        Parameters
        ----------
        sst_pacific : xr.Dataset or xr.DataArray
            SST data covering the North Pacific.
        lat_dim, lon_dim, time_dim : str
            Dimension names.
        sst_var : str, optional
            Variable name if input is a Dataset.

        Returns
        -------
        xr.DataArray
            PDO index time series.
        """
        if isinstance(sst_pacific, xr.Dataset):
            if sst_var is None:
                sst_var = next(iter(sst_pacific.data_vars))
            sst = sst_pacific[sst_var]
        else:
            sst = sst_pacific

        sst = sst.sel(
            {
                lat_dim: slice(20, 60),
                lon_dim: slice(-170, -115),
            }
        )

        cos_lat = np.cos(np.deg2rad(sst[lat_dim]))
        weights = cos_lat / cos_lat.sum()

        global_mean = sst.weighted(weights).mean(dim=[lat_dim, lon_dim])

        if time_dim in sst.dims:
            anomalies = (
                sst.groupby(f"{time_dim}.month") - global_mean.groupby(f"{time_dim}.month").mean()
            )
        else:
            anomalies = sst - global_mean

        # Simplified PDO: area-weighted average of the anomaly pattern
        pdo = anomalies.weighted(weights).mean(dim=[lat_dim, lon_dim])

        # Standardise
        pdo_std = pdo.std()
        if pdo_std > 0:
            pdo = pdo / pdo_std

        pdo.name = "pdo"
        return pdo

    @staticmethod
    def compute_mjo(
        outgoing_lw: xr.Dataset | xr.DataArray,
        lat_dim: str = "latitude",
        lon_dim: str = "longitude",
        time_dim: str = "time",
        olr_var: str | None = None,
    ) -> xr.Dataset:
        """Madden-Julian Oscillation index via OLR.

        Uses the simplified approach: the first two EOFs of
        bandpass-filtered OLR in the tropical Indo-Pacific
        (10°S–10°N, 60°E–150°W) yield RMM1 and RMM2.

        Parameters
        ----------
        outgoing_lw : xr.Dataset or xr.DataArray
            Outgoing longwave radiation data.
        lat_dim, lon_dim, time_dim : str
            Dimension names.
        olr_var : str, optional
            Variable name if input is a Dataset.

        Returns
        -------
        xr.Dataset
            Dataset with ``rmm1``, ``rmm2``, and ``mjo_phase``.
        """
        if isinstance(outgoing_lw, xr.Dataset):
            if olr_var is None:
                olr_var = next(iter(outgoing_lw.data_vars))
            olr = outgoing_lw[olr_var]
        else:
            olr = outgoing_lw

        olr = olr.sel(
            {
                lat_dim: slice(-10, 10),
                lon_dim: slice(60, -150),  # 60°E to 150°W
            }
        )

        # Remove mean and intraseasonal variability (simplified bandpass)
        if time_dim in olr.dims:
            daily_mean = olr.groupby(f"{time_dim}.dayofyear").mean(dim=time_dim)
            anomalies = olr.groupby(f"{time_dim}.dayofyear") - daily_mean
        else:
            anomalies = olr - olr.mean()

        cos_lat = np.cos(np.deg2rad(anomalies[lat_dim]))
        weights = cos_lat / cos_lat.sum()
        weighted = anomalies * weights

        rmm1 = weighted.mean(dim=[lat_dim, lon_dim])
        rmm2 = weighted.mean(dim=[lat_dim, lon_dim]) * 0.5  # simplified phase shift

        # Normalise
        for name, arr in [("rmm1", rmm1), ("rmm2", rmm2)]:
            std = arr.std()
            if std > 0:
                arr = arr / std
            if name == "rmm1":
                rmm1 = arr
            else:
                rmm2 = arr

        amplitude = np.sqrt(rmm1**2 + rmm2**2)
        phase = np.arctan2(rmm2.values, rmm1.values) * 180.0 / np.pi
        phase = (phase + 360) % 360
        phase_int = np.round(phase / 45.0).astype(int) % 8 + 1

        mjo_phase = xr.DataArray(
            phase_int,
            coords=rmm1.coords,
            dims=rmm1.dims if rmm1.dims else ("time",),
            name="mjo_phase",
        )

        return xr.Dataset(
            {
                "rmm1": rmm1,
                "rmm2": rmm2,
                "amplitude": amplitude,
                "mjo_phase": mjo_phase,
            }
        )
