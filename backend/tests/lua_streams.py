"""Executes the real retention/janitor Lua against an in-memory Redis stream model.

fakeredis cannot run XINFO inside scripts, and CI must not need a Redis server, so
this harness runs the exact production scripts in Lua (lupa, a locked fakeredis
extra) with ``redis.call`` implemented in Python for the stream commands used.
Values are bytes like a decode_responses=False client. Deliberately small: only
the commands and reply shapes the scripts and StreamRetention consume.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

# Lua 5.1 like Redis; the same module fakeredis loads (mixing lupa runtimes crashes).
from lupa.lua51 import LuaError, LuaRuntime
from redis.exceptions import ResponseError


def _key(entry_id: bytes) -> tuple[int, int]:
    major, minor = entry_id.split(b"-")
    return int(major), int(minor)


def _b(value) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode()


@dataclass
class Group:
    last: bytes = b"0-0"
    entries_read: int | None = 0
    pending: dict = field(default_factory=dict)  # id -> [consumer, delivered_at_ms, count]
    consumers: dict = field(default_factory=dict)  # name -> last_seen_ms


class LuaStreams:
    """Minimal async Redis double for StreamRetention + real Lua execution."""

    def __init__(self):
        self.streams: dict[bytes, list] = {}
        self.groups: dict[bytes, dict[bytes, Group]] = {}
        self.last_generated: dict[bytes, bytes] = {}
        self.memory = {"used_memory": 1, "maxmemory": 1000, "maxmemory_policy": "noeviction"}
        self.hooks: list = []  # callables(script) run before each eval (race injection)
        self.failing: set[bytes] = set()  # command names that return an error reply

        class Pool:
            connection_kwargs = {"decode_responses": False}

        self.connection_pool = Pool()
        self.lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)

    # ── model helpers ─────────────────────────────────────────────────────
    def add(self, stream, entry_id, *fields):
        stream, entry_id = _b(stream), _b(entry_id)
        rows = self.streams.setdefault(stream, [])
        assert not rows or _key(rows[-1][0]) < _key(entry_id)
        rows.append((entry_id, [_b(item) for item in fields]))
        self.last_generated[stream] = entry_id

    def create_group(self, stream, name, last=b"0-0"):
        self.groups.setdefault(_b(stream), {})[_b(name)] = Group(last=_b(last))

    def deliver(self, stream, name, consumer, count=None):
        stream, name, consumer = _b(stream), _b(name), _b(consumer)
        group = self.groups[stream][name]
        now = int(time.time() * 1000)
        group.consumers[consumer] = now
        delivered = []
        for entry_id, _ in self.streams.get(stream, []):
            if _key(entry_id) > _key(group.last) and (count is None or len(delivered) < count):
                group.pending[entry_id] = [consumer, now, 1]
                group.last = entry_id
                group.entries_read = (group.entries_read or 0) + 1
                delivered.append(entry_id)
        return delivered

    def ack(self, stream, name, *ids):
        group = self.groups[_b(stream)][_b(name)]
        for entry_id in ids:
            group.pending.pop(_b(entry_id), None)

    # ── Redis command semantics used by the scripts ───────────────────────
    def _range(self, stream, start, end, count=None):
        def bound(value, low):
            if value in (b"-", b"+"):
                return None, False
            exclusive = value.startswith(b"(")
            return _key(value[1:] if exclusive else value), exclusive

        lower, lower_x = bound(start, True)
        upper, upper_x = bound(end, False)
        rows = []
        for entry_id, fields in self.streams.get(stream, []):
            identity = _key(entry_id)
            if lower is not None and (identity < lower or (lower_x and identity == lower)):
                continue
            if upper is not None and (identity > upper or (upper_x and identity == upper)):
                continue
            rows.append([entry_id, list(fields)])
            if count is not None and len(rows) >= count:
                break
        return rows

    def _lag(self, stream, group):
        if group.entries_read is None:
            return None
        return len([1 for entry_id, _ in self.streams.get(stream, []) if _key(entry_id) > _key(group.last)])

    def command(self, *args):
        name = args[0].upper()
        if name in self.failing:
            raise ResponseError("OOM command not allowed when used memory > 'maxmemory'")
        if name == b"XINFO" and args[1].upper() == b"STREAM":
            stream = args[2]
            if stream not in self.streams:
                raise ResponseError("ERR no such key")
            return [b"length", len(self.streams[stream]), b"groups", len(self.groups.get(stream, {})),
                    b"last-generated-id", self.last_generated.get(stream, b"0-0")]
        if name == b"XINFO" and args[1].upper() == b"GROUPS":
            stream = args[2]
            rows = []
            for group_name, group in self.groups.get(stream, {}).items():
                rows.append([b"name", group_name, b"consumers", len(group.consumers),
                             b"pending", len(group.pending), b"last-delivered-id", group.last,
                             b"entries-read", group.entries_read, b"lag", self._lag(stream, group)])
            return rows
        if name == b"XINFO" and args[1].upper() == b"CONSUMERS":
            group = self.groups[args[2]][args[3]]
            now = int(time.time() * 1000)
            return [[b"name", consumer, b"pending", sum(1 for item in group.pending.values() if item[0] == consumer),
                     b"idle", now - seen] for consumer, seen in group.consumers.items()]
        if name == b"XGROUP" and args[1].upper() == b"DELCONSUMER":
            group = self.groups[args[2]][args[3]]
            removed = [entry_id for entry_id, item in group.pending.items() if item[0] == args[4]]
            for entry_id in removed:
                del group.pending[entry_id]
            group.consumers.pop(args[4], None)
            return len(removed)
        if name == b"XPENDING":
            group = self.groups[args[1]][args[2]]
            if not group.pending:
                return [0, None, None, None]
            ids = sorted(group.pending, key=_key)
            holders: dict = {}
            for item in group.pending.values():
                holders[item[0]] = holders.get(item[0], 0) + 1
            return [len(ids), ids[0], ids[-1], [[consumer, _b(total)] for consumer, total in holders.items()]]
        if name == b"XRANGE":
            count = int(args[5]) if len(args) > 5 else None
            return self._range(args[1], args[2], args[3], count)
        if name == b"XDEL":
            stream = args[1]
            before = len(self.streams.get(stream, []))
            targets = set(args[2:])
            self.streams[stream] = [row for row in self.streams.get(stream, []) if row[0] not in targets]
            return before - len(self.streams[stream])
        if name == b"XADD":
            entry_id = args[2]
            if entry_id == b"*":
                previous = _key(self.last_generated.get(args[1], b"0-0"))
                now = int(time.time() * 1000)
                entry_id = (f"{now}-0" if now > previous[0] else f"{previous[0]}-{previous[1] + 1}").encode()
            self.add(args[1], entry_id, *args[3:])
            return entry_id
        if name == b"EXISTS":
            return 1 if args[1] in self.streams else 0
        raise ResponseError(f"unsupported command {name!r}")

    # ── Lua bridge ────────────────────────────────────────────────────────
    def _to_lua(self, value):
        if isinstance(value, (list, tuple)):
            return self.lua.table_from([self._to_lua(item) for item in value])
        if value is None:
            return False
        if isinstance(value, str):
            return value.encode()
        return value

    def _from_lua(self, value):
        if value is None or value is False:
            return None
        if hasattr(value, "values") and hasattr(value, "keys"):
            return [self._from_lua(value[index]) for index in range(1, len(value) + 1)]
        return value

    async def eval(self, script, numkeys, *args):
        for hook in list(self.hooks):
            await hook(script)
        values = [_b(item) for item in args]
        keys, argv = values[:numkeys], values[numkeys:]

        def call(*command):
            # A Python exception aborts the script, like a Redis error reply.
            return self._to_lua(self.command(*command))

        def decode(text):
            return self._to_lua(json.loads(text))

        def encode(table):
            def plain(value):
                if isinstance(value, list):
                    return [plain(item) for item in value]
                return value.decode() if isinstance(value, bytes) else value
            return json.dumps(plain(self._from_lua(table)), separators=(",", ":")).encode()

        env = self.lua.eval("function(call, decode, encode) redis = {call = call}; "
                            "cjson = {decode = decode, encode = encode} end")
        env(call, decode, encode)
        globals_ = self.lua.globals()
        globals_.KEYS = self._to_lua(keys)
        globals_.ARGV = self._to_lua(argv)
        try:
            result = self.lua.execute(script)
        except LuaError as exc:
            raise ResponseError(str(exc)) from None
        return self._from_lua(result)

    # ── redis-py style helpers consumed by StreamRetention ────────────────
    async def info(self, section=None):
        return dict(self.memory)

    async def time(self):
        now = time.time()
        return int(now), int((now % 1) * 1_000_000)

    async def xinfo_stream(self, stream):
        stream = _b(stream)
        if stream not in self.streams:
            raise ResponseError("ERR no such key")
        rows = self.streams[stream]
        return {"length": len(rows), "groups": len(self.groups.get(stream, {})),
                "first-entry": (rows[0][0], rows[0][1]) if rows else None}

    async def xinfo_groups(self, stream):
        stream = _b(stream)
        return [{"name": name, "consumers": len(group.consumers), "pending": len(group.pending),
                 "last-delivered-id": group.last, "entries-read": group.entries_read,
                 "lag": self._lag(stream, group)} for name, group in self.groups.get(stream, {}).items()]

    async def xpending(self, stream, group):
        count, first, last, holders = self.command(b"XPENDING", _b(stream), _b(group))
        return {"pending": count, "min": first, "max": last,
                "consumers": [{"name": name, "pending": int(total)} for name, total in holders or ()]}

    async def xpending_range(self, stream, group, min, max, count):
        return [{"time_since_delivered": 1}]

    async def exists(self, *keys):
        return sum(1 for key in keys if _b(key) in self.streams)

    async def xlen(self, stream):
        return len(self.streams.get(_b(stream), []))

    async def xrange(self, stream, min="-", max="+", count=None):
        rows = self._range(_b(stream), _b(min), _b(max), count)
        # redis-py shape: (id, {field: value}); repeated field names collapse.
        return [(entry_id, dict(zip(fields[::2], fields[1::2]))) for entry_id, fields in rows]

    async def scan(self, cursor=0, match=None, count=None):
        return 0, []

    async def aclose(self):
        self.closed = True
