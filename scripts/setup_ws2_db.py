#!/usr/bin/env python3
"""WS-2 T0: Initialize database schema."""

import sys

from pakhi.ws2.db import get_engine, init_db


def main():
    print("Connecting to local TimescaleDB instance...")
    # Default URL based on docker-compose.yml
    engine = get_engine("postgresql://postgres:postgres@localhost:5432/pakhi")

    try:
        print("Applying schemas (forecast_cycles, signals, metrics)...")
        init_db(engine)
        print("Database schema successfully initialized.")
    except Exception as e:
        print(f"Error initializing database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
