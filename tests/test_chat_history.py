import importlib.util
import json
import os
import pathlib
import sys
import types
import unittest


class FakeBatch:
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def delete_item(self, Key):
        self.table.deleted.append(Key)


class FakeTable:
    def __init__(self):
        self.deleted = []

    def query(self, **kwargs):
        if "ExclusiveStartKey" not in kwargs:
            return {
                "Items": [{"userId": "Ada", "timestamp": "1", "question": "Q1", "response": "A1"}],
                "LastEvaluatedKey": {"userId": "Ada", "timestamp": "1"},
            }
        return {"Items": [{"userId": "Ada", "timestamp": "2", "question": "Q2", "response": "A2"}]}

    def batch_writer(self):
        return FakeBatch(self)


def load_module(table):
    os.environ.setdefault("HISTORY_TABLE", "test-history")
    boto3 = types.ModuleType("boto3")
    boto3.resource = lambda *_args, **_kwargs: types.SimpleNamespace(Table=lambda _name: table)
    dynamodb = types.ModuleType("boto3.dynamodb")
    conditions = types.ModuleType("boto3.dynamodb.conditions")
    conditions.Key = lambda name: types.SimpleNamespace(eq=lambda value: (name, value))
    replacements = {
        "boto3": boto3,
        "boto3.dynamodb": dynamodb,
        "boto3.dynamodb.conditions": conditions,
    }
    previous = {name: sys.modules.get(name) for name in replacements}
    sys.modules.update(replacements)
    backend = pathlib.Path(__file__).parents[1] / "backend"
    sys.path.insert(0, str(backend))
    try:
        path = backend / "chat_history.py"
        spec = importlib.util.spec_from_file_location("chat_history_test_module", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(backend))
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class ChatHistoryTest(unittest.TestCase):
    def test_list_returns_all_paginated_turns(self):
        module = load_module(FakeTable())
        result = module.handler({
            "requestContext": {"http": {"method": "GET"}},
            "queryStringParameters": {"userId": "Ada"},
        }, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual([item["question"] for item in json.loads(result["body"])["history"]], ["Q1", "Q2"])

    def test_clear_deletes_every_paginated_turn(self):
        table = FakeTable()
        module = load_module(table)
        result = module.handler({
            "requestContext": {"http": {"method": "DELETE"}},
            "body": json.dumps({"userId": "Ada"}),
        }, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"])["cleared"], 2)
        self.assertEqual(table.deleted, [
            {"userId": "Ada", "timestamp": "1"},
            {"userId": "Ada", "timestamp": "2"},
        ])


if __name__ == "__main__":
    unittest.main()
