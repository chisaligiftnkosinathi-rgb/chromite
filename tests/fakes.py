"""A small in-memory stand-in for the Supabase/PostgREST client used in API tests."""

from __future__ import annotations

from postgrest.exceptions import APIError


def api_error(code: str, message: str = "refused") -> APIError:
    return APIError({"code": code, "message": message, "details": None, "hint": None})


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str):
        self.client, self.table, self.op, self.payload, self.calls = client, table, "select", None, []

    def select(self, *args):
        self.calls.append(("select", *args))
        return self

    def insert(self, payload, **kwargs):
        self.op, self.payload = "insert", payload
        self.calls.append(("insert", payload, kwargs))
        return self

    def delete(self):
        self.op = "delete"
        self.calls.append(("delete",))
        return self

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, *args))
            return self
        return method

    def execute(self):
        self.client.log.append(self)
        result = self.client.handler(self)
        if isinstance(result, Exception):
            raise result
        return type("Response", (), {"data": result})()


class FakeClient:
    """`handler(query)` returns rows (list) or an Exception to raise."""

    def __init__(self, handler=None):
        self.handler = handler or (lambda q: [])
        self.log: list[FakeQuery] = []

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, params=None):
        q = FakeQuery(self, name)
        q.op, q.payload = "rpc", params
        q.calls.append(("rpc", name, params))
        return q

    def ops(self, table=None, op=None):
        return [q for q in self.log if (table is None or q.table == table) and (op is None or q.op == op)]
