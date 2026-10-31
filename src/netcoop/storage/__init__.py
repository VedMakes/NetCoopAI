"""Storage and persistence layer for NetCoop AI."""

from netcoop.storage.sqlite import SCHEMA_VERSION, SQLiteRepository

__all__ = ["SCHEMA_VERSION", "SQLiteRepository"]
