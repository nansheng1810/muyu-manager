import unittest
from unittest import mock

from server import api, knowledge


class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.inst = {"id": "i1", "name": "大肥鱼"}

    def test_routes_registered(self):
        paths = {getattr(route, "path", "") for route in api.app.routes}
        for path in (
            "/api/instances/{inst_id}/knowledge/bases",
            "/api/instances/{inst_id}/knowledge/providers",
            "/api/instances/{inst_id}/knowledge/bases/{kb_id}/documents",
            "/api/instances/{inst_id}/knowledge/bases/{kb_id}/retrieve",
        ):
            self.assertIn(path, paths)

    def test_list_bases_unwraps_dashboard_payload(self):
        with mock.patch.object(
            knowledge.dashboard, "call",
            return_value={"status": "ok", "data": {"items": [{"kb_id": "k1"}], "total": 1}},
        ) as call:
            data = knowledge.list_bases(self.inst, 1, 50)
        self.assertEqual(data["items"][0]["kb_id"], "k1")
        call.assert_called_once()
        self.assertEqual(call.call_args.kwargs["query"]["page_size"], 50)

    def test_create_validates_and_passes_chunk_size(self):
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.create_base(self.inst, {"name": ""})
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.create_base(self.inst, {"name": "群规"})
        with mock.patch.object(
            knowledge.dashboard, "call",
            return_value={"status": "ok", "data": {"kb_id": "k1"}},
        ) as call:
            data = knowledge.create_base(self.inst, {
                "name": "群规", "embedding_provider_id": "emb1", "chunk_size": 512,
            })
        self.assertEqual(data["kb_id"], "k1")
        body = call.call_args.args[3]
        self.assertEqual(body["name"], "群规")
        self.assertEqual(body["chunk_size"], 512)

    def test_retrieve_uses_kb_name(self):
        calls = []

        def fake_call(inst, method, path, payload=None, query=None, timeout=60):
            calls.append((method, path, payload))
            if path.endswith("/stats"):
                return {"status": "ok", "data": {"kb_name": "群规库"}}
            return {"status": "ok", "data": {"results": [{"content": "片段"}]}}

        with mock.patch.object(knowledge.dashboard, "call", side_effect=fake_call):
            data = knowledge.retrieve(self.inst, "k1", {"query": "怎么入群", "top_k": 3})
        self.assertEqual(data["results"][0]["content"], "片段")
        retrieve_call = [item for item in calls if "retrieve" in item[1]][0]
        self.assertEqual(retrieve_call[2]["kb_names"], ["群规库"])
        self.assertEqual(retrieve_call[2]["top_k"], 3)

    def test_import_urls_includes_kb_id(self):
        with mock.patch.object(
            knowledge.dashboard, "call",
            return_value={"status": "ok", "data": {"task_id": "t1"}},
        ) as call:
            knowledge.import_urls(self.inst, "k1", {"urls": ["https://example.com"]})
        body = call.call_args.args[3]
        self.assertEqual(body["kb_id"], "k1")
        self.assertEqual(body["urls"], ["https://example.com"])

    def test_embedding_providers_filters_type(self):
        with mock.patch.object(knowledge.dashboard, "call", return_value={
            "status": "ok",
            "data": [
                {"id": "c1", "type": "chat", "model": "gpt"},
                {"id": "e1", "type": "embedding", "model": "bge"},
            ],
        }):
            items = knowledge.embedding_providers(self.inst)
        self.assertEqual([item["id"] for item in items], ["e1"])


if __name__ == "__main__":
    unittest.main()
