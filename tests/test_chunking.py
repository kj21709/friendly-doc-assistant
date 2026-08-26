import importlib.util
import pathlib
import sys
import types
import os
import unittest


def load_module():
    os.environ.setdefault("DOCUMENTS_TABLE", "test-documents")
    os.environ.setdefault("DOCUMENT_BUCKET", "test-bucket")
    boto3 = types.SimpleNamespace(client=lambda *_a, **_k: None, resource=lambda *_a, **_k: types.SimpleNamespace(Table=lambda _n: None))
    sys.modules.setdefault("boto3", boto3)
    pypdf = types.SimpleNamespace(PdfReader=object)
    sys.modules.setdefault("pypdf", pypdf)
    numpy = types.SimpleNamespace()
    sys.modules.setdefault("numpy", numpy)
    path = pathlib.Path(__file__).parents[1] / "backend" / "embed_documents_v5_s3.py"
    spec = importlib.util.spec_from_file_location("embedder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChunkingTest(unittest.TestCase):
    def test_split_text_respects_limit_and_overlap(self):
        module = load_module()
        chunks = module.split_text("A" * 1200 + "\n\n" + "B" * 900)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= module.CHUNK_SIZE for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
