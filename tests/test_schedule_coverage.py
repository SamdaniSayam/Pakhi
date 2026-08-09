import pytest
from pakhi.pipeline.schedule import RefreshScheduler
from datetime import datetime, timezone
import threading
import time

def test_schedule_tick_exception():
    scheduler = RefreshScheduler(check_interval_seconds=1)
    
    def bad_callback():
        raise ValueError("mock error")
        
    scheduler.schedule_refresh(bad_callback, interval_hours=1, next_run_time=datetime.now(timezone.utc))
    
    # Manually trigger tick to execute the job and catch exception
    scheduler._tick()
    
    # We should also stop it so it doesn't hang
    scheduler.stop()
