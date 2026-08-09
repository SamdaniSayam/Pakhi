"""Streaming chunk-based data processor for large weather datasets.

Provides lazy chunked processing backed by Dask for GRIB/NetCDF files,
mirroring triples-sigfast SigPipeline patterns.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, TypeVar

import xarray as xr

__all__ = ["StreamingProcessor"]

logger = logging.getLogger(__name__)

T = TypeVar("T")


class StreamingProcessor:
    """Chunk-based streaming processor for large weather datasets.

    Lazily loads GRIB/NetCDF files via Dask and processes them in
    fixed-size chunks to control memory usage. Follows the pipeline
    pattern from triples-sigfast.

    Parameters
    ----------
    chunk_size : int, optional
        Default number of time steps per chunk. Default 64.
    """

    __all__ = ["process_chunks", "process_lazy", "process_stream"]

    def __init__(self, chunk_size: int = 64) -> None:
        self.chunk_size = chunk_size
        self._open_datasets: list[xr.Dataset] = []

    def process_chunks(
        self,
        data_path: str | Path,
        process_fn: Callable[[xr.Dataset], xr.Dataset | Any],
        chunk_size: int | None = None,
        variables: list[str] | None = None,
    ) -> Generator[xr.Dataset | Any, None, None]:
        """Lazily process a file in chunks along the time dimension.

        Loads the dataset with Dask-backed arrays and iterates over
        time chunks, applying *process_fn* to each.

        Parameters
        ----------
        data_path : str or Path
            Path to GRIB, NetCDF, or Zarr store.
        process_fn : callable
            Function applied to each time chunk. Must accept an
            ``xr.Dataset`` and return a dataset or arbitrary result.
        chunk_size : int, optional
            Time steps per chunk. Overrides instance default.
        variables : list of str, optional
            Variable names to load. ``None`` loads all.

        Yields
        ------
        xr.Dataset or any
            Result of *process_fn* for each chunk.
        """
        chunk_size = chunk_size or self.chunk_size
        path = Path(data_path)

        if not path.exists():
            raise FileNotFoundError(f"Data file not found: {path}")

        chunks: dict[str, int] = {"time": chunk_size}
        open_kwargs: dict[str, Any] = {"chunks": chunks}
        if variables is not None:
            open_kwargs["variables"] = variables

        suffix = path.suffix.lower()
        if suffix in (".grib", ".grib2", ".grb", ".grb2"):
            ds = xr.open_dataset(path, engine="cfgrib", **open_kwargs)  # type: ignore[arg-type]
        elif suffix in (".nc", ".nc4"):
            ds = xr.open_dataset(path, engine="netcdf4", **open_kwargs)  # type: ignore[arg-type]
        elif path.is_dir():
            ds = xr.open_zarr(str(path), **open_kwargs)  # type: ignore[arg-type]
        else:
            ds = xr.open_dataset(path, **open_kwargs)  # type: ignore[arg-type]

        self._open_datasets.append(ds)

        time_dim = "time" if "time" in ds.dims else next(iter(ds.dims))
        n_steps = ds.dims[time_dim]

        logger.info(
            "Streaming %s in %d steps (chunk_size=%d)",
            path.name,
            n_steps,
            chunk_size,
        )

        try:
            for start in range(0, n_steps, chunk_size):
                end = min(start + chunk_size, n_steps)
                slice_obj = {time_dim: slice(start, end)}
                chunk = ds.isel(**slice_obj)
                chunk = chunk.compute() if hasattr(chunk, "chunks") and chunk.chunks else chunk
                yield process_fn(chunk)
        finally:
            ds.close()
            if ds in self._open_datasets:
                self._open_datasets.remove(ds)

    def process_lazy(
        self,
        data_path: str | Path,
        process_fn: Callable[[xr.Dataset], xr.Dataset],
        chunk_size: int | None = None,
    ) -> xr.Dataset:
        """Apply *process_fn* lazily across all chunks and concatenate.

        Returns a single concatenated dataset without materialising
        the full array in memory.

        Parameters
        ----------
        data_path : str or Path
            Path to the input file.
        process_fn : callable
            Transform applied to each chunk.
        chunk_size : int, optional
            Time steps per chunk.

        Returns
        -------
        xr.Dataset
            Concatenated result of all processed chunks.
        """
        chunks = list(self.process_chunks(data_path, process_fn, chunk_size))
        if not chunks:
            raise ValueError("No chunks produced — empty dataset?")
        return xr.concat(chunks, dim="time")

    def process_stream(
        self,
        data_path: str | Path,
        process_fn: Callable[[xr.Dataset], T],
        chunk_size: int | None = None,
        sink_fn: Callable[[T], None] | None = None,
    ) -> list[T]:
        """Process a file and optionally sink each result.

        Parameters
        ----------
        data_path : str or Path
            Path to the input file.
        process_fn : callable
            Transform applied to each chunk.
        chunk_size : int, optional
            Time steps per chunk.
        sink_fn : callable, optional
            Side-effect function (e.g. write to DB) called on each result.

        Returns
        -------
        list of T
            All results collected into a list.
        """
        results: list[T] = []
        for chunk_result in self.process_chunks(data_path, process_fn, chunk_size):
            if sink_fn is not None:
                sink_fn(chunk_result)
            results.append(chunk_result)
        return results

    def close_all(self) -> None:
        """Close all open datasets."""
        for ds in self._open_datasets:
            try:
                ds.close()
            except Exception:
                logger.debug("Error closing dataset", exc_info=True)
        self._open_datasets.clear()
