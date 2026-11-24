from __future__ import annotations

import unittest
import uuid
from dataclasses import dataclass

from pymilvus import MilvusClient

from backend.app.config import EMBEDDING_DIM, MILVUS_URI
from backend.app.services.milvus_repo import MILVUS_DATABASE, MilvusRepo


@dataclass
class _Chunk:
    id: str
    chapter: int
    chapter_title: str
    text: str
    tokens: int
    source: str = "西游记.txt"


class MilvusRepoIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = MilvusRepo()
        cls.default_client = MilvusClient(uri=MILVUS_URI)
        cls.project_client = MilvusClient(uri=MILVUS_URI, db_name=MILVUS_DATABASE)
        cls.default_collections_before = set(cls.default_client.list_collections())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.default_collections_after = set(cls.default_client.list_collections())
        if cls.default_collections_before != cls.default_collections_after:
            raise AssertionError(
                "default 数据库集合发生变化: "
                f"before={sorted(cls.default_collections_before)} "
                f"after={sorted(cls.default_collections_after)}"
            )

    def test_uses_rag_demo_database(self) -> None:
        self.assertEqual(self.repo.database, MILVUS_DATABASE)
        self.assertIn(MILVUS_DATABASE, self.default_client.list_databases())

    def test_collection_lifecycle_stays_in_project_database(self) -> None:
        collection = f"rag_demo_isolation_{uuid.uuid4().hex[:10]}"
        chunk = _Chunk(
            id="iso0001",
            chapter=1,
            chapter_title="测试回",
            text="孙悟空腾空而起，翻筋斗云远去。",
            tokens=12,
        )
        vector = [0.0] * EMBEDDING_DIM

        try:
            inserted = self.repo.insert_chunks(collection, [chunk], [vector])
            self.assertEqual(inserted, 1)
            self.assertIn(collection, self.project_client.list_collections())
            self.assertNotIn(collection, self.default_client.list_collections())
            self.assertEqual(self.repo.count(collection), 1)
            row = self.repo.get_chunk(collection, chunk.id)
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row.get("chunk_id"), chunk.id)
        finally:
            self.repo.drop_collection(collection)
            self.assertNotIn(collection, self.project_client.list_collections())


if __name__ == "__main__":
    unittest.main()
