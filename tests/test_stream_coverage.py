import pytest
from pakhi.pipeline.stream import StreamingProcessor
import xarray as xr

def test_stream_process_chunks_other_suffix(tmp_path):
    # create a mock file with .dat suffix
    ds = xr.Dataset({"a": ("time", [1, 2, 3])})
    path = tmp_path / "mock.dat"
    ds.to_netcdf(path)
    
    processor = StreamingProcessor()
    # It should fall back to xr.open_dataset
    res = list(processor.process_chunks(path, lambda x: x))
    assert len(res) > 0
