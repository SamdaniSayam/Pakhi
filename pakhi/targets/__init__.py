"""Pakhi target variable modules.

Re-exports all public functions from the submodules for convenient access::

    from pakhi.targets import heat_index, power_curve, saffir_simpson
"""

from pakhi.targets.hurricane import (
    rainfall_accumulation,
    rapid_intensification_probability,
    saffir_simpson,
    wind_radius_estimate,
)
from pakhi.targets.precipitation import (
    drought_index,
    precipitation_accumulation,
    rain_days_probability,
    snow_probability,
)
from pakhi.targets.pressure import (
    central_pressure_to_category,
    pressure_gradient_force,
    pressure_tendency,
    storm_surge_estimate,
)
from pakhi.targets.solar import (
    clear_sky_radiation,
    ghi_from_cloud_cover,
    photovoltaic_output,
    solar_position,
)
from pakhi.targets.temperature import (
    diurnal_temperature_range,
    freeze_probability,
    growing_degree_days,
    heat_index,
    wind_chill,
)
from pakhi.targets.wind import (
    beaufort_scale,
    power_curve,
    wind_direction_components,
    wind_power_forecast,
)

__all__ = [
    "beaufort_scale",
    # pressure
    "central_pressure_to_category",
    "clear_sky_radiation",
    "diurnal_temperature_range",
    "drought_index",
    # temperature
    "freeze_probability",
    "ghi_from_cloud_cover",
    "growing_degree_days",
    "heat_index",
    "photovoltaic_output",
    # wind
    "power_curve",
    # precipitation
    "precipitation_accumulation",
    "pressure_gradient_force",
    "pressure_tendency",
    "rain_days_probability",
    "rainfall_accumulation",
    "rapid_intensification_probability",
    # hurricane
    "saffir_simpson",
    "snow_probability",
    # solar
    "solar_position",
    "storm_surge_estimate",
    "wind_chill",
    "wind_direction_components",
    "wind_power_forecast",
    "wind_radius_estimate",
]
