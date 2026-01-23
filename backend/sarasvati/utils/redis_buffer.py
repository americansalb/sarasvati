"""
SARASVATI Redis Buffer Manager
===============================
Redis-backed FIFO buffer for temporal alignment "Hot Buffer."

This module provides efficient buffer management using Redis Stack
with RediSearch for fast semantic similarity queries.
"""

import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import asyncio

try:
    import redis.asyncio as redis
    from redis.commands.search.field import TextField, NumericField, VectorField
    from redis.commands.search.indexDefinition import IndexDefinition, IndexType
    from redis.commands.search.query import Query
except ImportError:
    redis = None

from ..core.state import BufferEntry, TranscriptSegment, StreamRole


class RedisBufferConfig:
    """Configuration for Redis buffer."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_buffer_size: int = 100,
        ttl_seconds: int = 3600,  # 1 hour TTL
        enable_vector_search: bool = True,
        vector_dim: int = 384,
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.max_buffer_size = max_buffer_size
        self.ttl_seconds = ttl_seconds
        self.enable_vector_search = enable_vector_search
        self.vector_dim = vector_dim


class RedisBuffer:
    """
    Redis-backed FIFO buffer with vector search capabilities.

    This provides:
    1. FIFO queue for transcript segments
    2. Fast semantic similarity search using RediSearch
    3. Automatic expiration of old entries
    4. Persistent storage across restarts
    """

    def __init__(self, config: RedisBufferConfig):
        if redis is None:
            raise ImportError(
                "redis package not installed. Install with: pip install redis[hiredis]"
            )

        self.config = config
        self.client: Optional[redis.Redis] = None
        self._is_connected = False

    async def connect(self) -> None:
        """
        Establish connection to Redis.
        PHASE 1 FIX: Added connection pooling for better resource management.
        """
        # PHASE 1 FIX: Use connection pool instead of direct connection
        pool = redis.ConnectionPool(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            password=self.config.password,
            max_connections=10,  # Connection pool size
            decode_responses=False,
        )

        self.client = redis.Redis(connection_pool=pool)

        # Test connection with retry
        try:
            await self._retry_operation(self.client.ping)
            self._is_connected = True
            print(f"✅ Connected to Redis at {self.config.host}:{self.config.port} (pool size: 10)")

            # Initialize search index if vector search enabled
            if self.config.enable_vector_search:
                await self._create_search_index()

        except Exception as e:
            print(f"❌ Redis connection failed after retries: {e}")
            raise

    async def _retry_operation(self, operation, max_retries: int = 3, backoff_seconds: float = 1.0):
        """
        PHASE 1 FIX: Retry Redis operations with exponential backoff.

        Args:
            operation: Async callable to retry
            max_retries: Maximum retry attempts
            backoff_seconds: Initial backoff time (doubles each retry)

        Returns:
            Result of the operation
        """
        import asyncio

        last_error = None
        for attempt in range(max_retries):
            try:
                return await operation()
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = backoff_seconds * (2 ** attempt)
                    print(f"⚠️  Redis operation failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"❌ Redis operation failed after {max_retries} attempts: {e}")

        raise last_error

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            self._is_connected = False

    async def push(
        self,
        session_id: str,
        role: StreamRole,
        entry: BufferEntry,
    ) -> None:
        """
        Push a new entry to the buffer.

        Args:
            session_id: Session identifier
            role: Stream role (provider/interpreter/patient)
            entry: Buffer entry to push
        """
        if not self._is_connected:
            raise RuntimeError("Not connected to Redis")

        # Create key for this buffer
        key = self._get_buffer_key(session_id, role)

        # Serialize entry
        entry_json = self._serialize_entry(entry)

        # Push to list (FIFO: LPUSH + LTRIM)
        await self.client.lpush(key, entry_json)

        # Trim to max size
        await self.client.ltrim(key, 0, self.config.max_buffer_size - 1)

        # Set TTL
        await self.client.expire(key, self.config.ttl_seconds)

        # If vector search enabled, index the entry
        if self.config.enable_vector_search:
            await self._index_entry(session_id, role, entry)

    async def get_all(
        self,
        session_id: str,
        role: StreamRole,
    ) -> List[BufferEntry]:
        """
        Get all entries from buffer.

        PHASE 1 FIX: Extends TTL on read to prevent expiration during processing.

        Args:
            session_id: Session identifier
            role: Stream role

        Returns:
            List of buffer entries
        """
        if not self._is_connected:
            raise RuntimeError("Not connected to Redis")

        key = self._get_buffer_key(session_id, role)

        # PHASE 1 FIX: Extend TTL before reading to prevent race condition
        # If buffer expires between read and processing, data is lost
        await self.client.expire(key, self.config.ttl_seconds)

        # Get all entries (newest first)
        entries_json = await self.client.lrange(key, 0, -1)

        entries = [
            self._deserialize_entry(entry_bytes)
            for entry_bytes in entries_json
        ]

        return entries

    async def get_range(
        self,
        session_id: str,
        role: StreamRole,
        start: int,
        end: int,
    ) -> List[BufferEntry]:
        """
        Get a range of entries from buffer.

        Args:
            session_id: Session identifier
            role: Stream role
            start: Start index (0 = newest)
            end: End index (-1 = oldest)

        Returns:
            List of buffer entries
        """
        if not self._is_connected:
            raise RuntimeError("Not connected to Redis")

        key = self._get_buffer_key(session_id, role)
        entries_json = await self.client.lrange(key, start, end)

        entries = [
            self._deserialize_entry(entry_bytes)
            for entry_bytes in entries_json
        ]

        return entries

    async def search_semantic(
        self,
        session_id: str,
        role: StreamRole,
        query_vector: List[float],
        k: int = 10,
    ) -> List[BufferEntry]:
        """
        Semantic similarity search using vector embeddings.

        This is the key feature for the alignment problem - we can find
        semantically similar segments even if they're temporally offset.

        Args:
            session_id: Session identifier
            role: Stream role to search
            query_vector: Query embedding vector
            k: Number of results to return

        Returns:
            List of buffer entries sorted by similarity
        """
        if not self._is_connected or not self.config.enable_vector_search:
            # Fallback to get_all if vector search not available
            return await self.get_all(session_id, role)

        try:
            # Create vector query
            index_name = self._get_index_name(session_id, role)

            # Format vector for Redis query
            vec_str = ",".join([str(v) for v in query_vector])

            # Build query
            query = (
                Query(f"*=>[KNN {k} @embedding $vec AS score]")
                .sort_by("score")
                .return_fields("entry_data", "score")
                .dialect(2)
            )

            # Execute search
            results = await self.client.ft(index_name).search(
                query,
                query_params={"vec": vec_str},
            )

            # Parse results
            entries = []
            for doc in results.docs:
                entry_data = doc.entry_data
                entry = self._deserialize_entry(entry_data)
                entries.append(entry)

            return entries

        except Exception as e:
            print(f"⚠️  Vector search failed: {e}")
            # Fallback to linear scan
            return await self.get_all(session_id, role)

    async def clear(
        self,
        session_id: str,
        role: Optional[StreamRole] = None,
    ) -> None:
        """
        Clear buffer(s) for a session.

        Args:
            session_id: Session identifier
            role: If specified, clear only this role's buffer.
                  If None, clear all buffers for session.
        """
        if not self._is_connected:
            raise RuntimeError("Not connected to Redis")

        if role:
            key = self._get_buffer_key(session_id, role)
            await self.client.delete(key)
        else:
            # Clear all buffers for session
            for role_val in StreamRole:
                key = self._get_buffer_key(session_id, role_val)
                await self.client.delete(key)

    async def get_size(
        self,
        session_id: str,
        role: StreamRole,
    ) -> int:
        """Get current size of buffer."""
        if not self._is_connected:
            raise RuntimeError("Not connected to Redis")

        key = self._get_buffer_key(session_id, role)
        return await self.client.llen(key)

    # ===== Private Methods =====

    def _get_buffer_key(self, session_id: str, role: StreamRole) -> str:
        """Generate Redis key for buffer."""
        return f"sarasvati:buffer:{session_id}:{role.value}"

    def _get_index_name(self, session_id: str, role: StreamRole) -> str:
        """Generate index name for vector search."""
        return f"idx:sarasvati:{session_id}:{role.value}"

    def _serialize_entry(self, entry: BufferEntry) -> bytes:
        """Serialize buffer entry to JSON bytes."""
        # Convert datetime to ISO format
        entry_dict = dict(entry)
        entry_dict["buffered_at"] = entry["buffered_at"].isoformat()

        return json.dumps(entry_dict).encode("utf-8")

    def _deserialize_entry(self, data: bytes) -> BufferEntry:
        """Deserialize buffer entry from JSON bytes."""
        entry_dict = json.loads(data.decode("utf-8"))

        # Convert ISO format back to datetime
        entry_dict["buffered_at"] = datetime.fromisoformat(
            entry_dict["buffered_at"]
        )

        return BufferEntry(**entry_dict)

    async def _create_search_index(self) -> None:
        """
        Create RediSearch index for vector similarity search.
        PHASE 1 FIX: Added validation and fallback detection.
        """
        # Note: In production, create one index per session+role
        # For MVP, we'll create a generic index structure

        index_name = "idx:sarasvati:global"

        try:
            # Check if index exists
            await self.client.ft(index_name).info()
            print(f"✅ Search index '{index_name}' already exists")
            return
        except:
            pass  # Index doesn't exist, create it

        # Define schema
        schema = (
            TextField("text"),
            NumericField("timestamp"),
            VectorField(
                "embedding",
                "FLAT",
                {
                    "TYPE": "FLOAT32",
                    "DIM": self.config.vector_dim,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
        )

        # Create index
        try:
            await self.client.ft(index_name).create_index(
                fields=schema,
                definition=IndexDefinition(
                    prefix=["sarasvati:vec:"],
                    index_type=IndexType.HASH,
                ),
            )
            print(f"✅ Created search index '{index_name}'")

            # PHASE 1 FIX: Validate index creation succeeded
            try:
                index_info = await self.client.ft(index_name).info()
                print(f"✅ Index validation passed - {index_info.get('num_docs', 0)} docs indexed")
            except Exception as validation_error:
                print(f"⚠️  WARNING: Index created but validation failed: {validation_error}")
                print(f"   Vector search will fall back to O(n) linear scan")
                # PHASE 1 FIX: Emit metric for monitoring
                self._emit_metric("redis.index_validation_failed", 1)

        except Exception as e:
            print(f"⚠️  Index creation failed (may already exist): {e}")
            print(f"   Vector search will fall back to O(n) linear scan")
            # PHASE 1 FIX: Emit metric for monitoring
            self._emit_metric("redis.index_creation_failed", 1)

    def _emit_metric(self, metric_name: str, value: float) -> None:
        """
        PHASE 1 FIX: Emit metrics for monitoring (stub for now, integrate with your metrics system).

        Args:
            metric_name: Metric name (e.g., "redis.vector_search_failure")
            value: Metric value
        """
        # TODO: Integrate with Prometheus/StatsD/CloudWatch
        print(f"📊 METRIC: {metric_name} = {value}")

    async def _index_entry(
        self,
        session_id: str,
        role: StreamRole,
        entry: BufferEntry,
    ) -> None:
        """Index an entry for vector search."""
        # Note: This requires embeddings to be pre-computed
        # In production, compute embeddings before calling push()

        segment = entry["segment"]

        # Skip if no text
        if not segment["text"]:
            return

        # Create document key
        doc_key = (
            f"sarasvati:vec:{session_id}:{role.value}:"
            f"{segment['timestamp']}"
        )

        # For MVP, we don't have real embeddings yet
        # In production, this would store the actual embedding vector
        # For now, just store the text for future indexing

        doc_data = {
            "text": segment["text"],
            "timestamp": segment["timestamp"],
            "role": role.value,
            "session_id": session_id,
            "entry_data": self._serialize_entry(entry),
        }

        # Store document (without embedding for MVP)
        await self.client.hset(doc_key, mapping=doc_data)
        await self.client.expire(doc_key, self.config.ttl_seconds)


class RedisSessionManager:
    """
    Manages session metadata in Redis.

    Tracks active sessions, stats, and configuration.
    """

    def __init__(self, buffer: RedisBuffer):
        self.buffer = buffer

    async def create_session(
        self,
        session_id: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Create a new session with metadata."""
        key = f"sarasvati:session:{session_id}:meta"

        session_data = {
            "session_id": session_id,
            "created_at": datetime.utcnow().isoformat(),
            "status": "active",
            **metadata,
        }

        await self.buffer.client.hset(
            key,
            mapping={k: json.dumps(v) for k, v in session_data.items()},
        )

        # Set TTL
        await self.buffer.client.expire(key, self.buffer.config.ttl_seconds)

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata."""
        key = f"sarasvati:session:{session_id}:meta"

        data = await self.buffer.client.hgetall(key)

        if not data:
            return None

        return {
            k.decode("utf-8"): json.loads(v.decode("utf-8"))
            for k, v in data.items()
        }

    async def update_session_stats(
        self,
        session_id: str,
        stats: Dict[str, Any],
    ) -> None:
        """Update session statistics."""
        key = f"sarasvati:session:{session_id}:stats"

        await self.buffer.client.hset(
            key,
            mapping={k: json.dumps(v) for k, v in stats.items()},
        )

        await self.buffer.client.expire(key, self.buffer.config.ttl_seconds)

    async def end_session(self, session_id: str) -> None:
        """Mark session as ended."""
        key = f"sarasvati:session:{session_id}:meta"

        await self.buffer.client.hset(
            key,
            "status",
            json.dumps("ended"),
        )
        await self.buffer.client.hset(
            key,
            "ended_at",
            json.dumps(datetime.utcnow().isoformat()),
        )


# ===== Factory Functions =====

async def create_redis_buffer(
    host: str = "localhost",
    port: int = 6379,
    **kwargs,
) -> RedisBuffer:
    """
    Factory to create and connect Redis buffer.

    Args:
        host: Redis host
        port: Redis port
        **kwargs: Additional config options

    Returns:
        Connected RedisBuffer instance
    """
    config = RedisBufferConfig(host=host, port=port, **kwargs)
    buffer = RedisBuffer(config)
    await buffer.connect()
    return buffer
