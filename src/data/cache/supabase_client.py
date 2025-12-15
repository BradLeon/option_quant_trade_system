"""Supabase client wrapper for database operations."""

import logging
import os
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Wrapper for Supabase client with connection management."""

    _instance: Client | None = None
    _initialized: bool = False

    def __init__(self) -> None:
        """Initialize Supabase client from environment variables."""
        if not SupabaseClient._initialized:
            self._init_client()

    def _init_client(self) -> None:
        """Initialize the Supabase client."""
        load_dotenv()

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

        if not url or not key:
            logger.warning(
                "SUPABASE_URL or SUPABASE_KEY not set. "
                "Database caching will be disabled."
            )
            SupabaseClient._instance = None
            SupabaseClient._initialized = True
            return

        try:
            SupabaseClient._instance = create_client(url, key)
            SupabaseClient._initialized = True
            logger.info("Supabase client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            SupabaseClient._instance = None
            SupabaseClient._initialized = True

    @property
    def client(self) -> Client | None:
        """Get the Supabase client instance."""
        return SupabaseClient._instance

    @property
    def is_available(self) -> bool:
        """Check if Supabase client is available."""
        return SupabaseClient._instance is not None

    def table(self, table_name: str) -> Any:
        """Get a table reference for queries.

        Args:
            table_name: Name of the table to query.

        Returns:
            Table query builder or None if client unavailable.

        Raises:
            RuntimeError: If Supabase client is not available.
        """
        if not self.is_available:
            raise RuntimeError("Supabase client is not available")
        return self.client.table(table_name)

    def execute_query(
        self,
        table_name: str,
        operation: str,
        data: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a query on a table.

        Args:
            table_name: Name of the table.
            operation: One of 'select', 'insert', 'update', 'upsert', 'delete'.
            data: Data for insert/update/upsert operations.
            filters: Filters for select/update/delete operations.

        Returns:
            List of result records.

        Raises:
            RuntimeError: If Supabase client is not available.
            ValueError: If invalid operation is specified.
        """
        if not self.is_available:
            raise RuntimeError("Supabase client is not available")

        table = self.client.table(table_name)

        if operation == "select":
            query = table.select("*")
            if filters:
                for key, value in filters.items():
                    query = query.eq(key, value)
            response = query.execute()
        elif operation == "insert":
            if not data:
                raise ValueError("Data required for insert operation")
            response = table.insert(data).execute()
        elif operation == "upsert":
            if not data:
                raise ValueError("Data required for upsert operation")
            response = table.upsert(data).execute()
        elif operation == "update":
            if not data:
                raise ValueError("Data required for update operation")
            query = table.update(data)
            if filters:
                for key, value in filters.items():
                    query = query.eq(key, value)
            response = query.execute()
        elif operation == "delete":
            query = table.delete()
            if filters:
                for key, value in filters.items():
                    query = query.eq(key, value)
            response = query.execute()
        else:
            raise ValueError(f"Invalid operation: {operation}")

        return response.data if response.data else []

    @classmethod
    def reset(cls) -> None:
        """Reset the client instance (useful for testing)."""
        cls._instance = None
        cls._initialized = False
