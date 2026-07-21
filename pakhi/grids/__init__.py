"""Grid operations for gridded meteorological and climate data.

Re-exports all public functions from the submodules so that users can
access them directly::

    from pakhi.grids import bilinear_interpolation, subset_bbox, regrid
"""

from pakhi.grids.coordinate import (
    altitude_to_pressure,
    geopotential_to_height,
    km_to_latlon,
    latlon_to_km,
    pressure_to_altitude,
    validate_latlon,
)
from pakhi.grids.interpolate import (
    bilinear_interpolation,
    cressman_interpolation,
    inverse_distance_weighting,
    nearest_neighbor,
)
from pakhi.grids.regridder import (
    create_regular_grid,
    regrid,
    regrid_to_regular,
)
from pakhi.grids.subset import (
    subset_bbox,
    subset_country,
    subset_point,
    subset_polygon,
)

__all__ = [
    "altitude_to_pressure",
    # interpolate
    "bilinear_interpolation",
    "create_regular_grid",
    "cressman_interpolation",
    "geopotential_to_height",
    "inverse_distance_weighting",
    "km_to_latlon",
    # coordinate
    "latlon_to_km",
    "nearest_neighbor",
    "pressure_to_altitude",
    # regridder
    "regrid",
    "regrid_to_regular",
    # subset
    "subset_bbox",
    "subset_country",
    "subset_point",
    "subset_polygon",
    "validate_latlon",
]
