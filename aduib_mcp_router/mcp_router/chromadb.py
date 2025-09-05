import logging
import os
import shutil
from typing import Optional, List, Any

import chromadb
from chromadb import Settings, Metadata
from chromadb.api.types import OneOrMany, Document, ID, QueryResult, GetResult
from chromadb.types import Collection

logger=logging.getLogger(__name__)

class ChromaDB:
    """very basic wrapper around chromadb"""

    def __init__(self, router_home: str) -> None:
        home_chroma_db_ = os.path.join(router_home, 'chromadb')
        if not os.path.exists(home_chroma_db_):
            os.makedirs(home_chroma_db_, exist_ok=True)
        else:
            shutil.rmtree(home_chroma_db_, ignore_errors=True)
        self.dbClient = chromadb.PersistentClient(path=home_chroma_db_,
                                                  settings=Settings(
                                                      is_persistent=True,
                                                      anonymized_telemetry=False,
                                                  ))
        self.preIds = []
        self.collections: dict[str, Collection] = {}

    def create_collection(self, collection_name: str) -> str:
        _collectionId = "aduib_mcp_router_" + collection_name
        _collection = self.dbClient.get_or_create_collection(_collectionId)
        self.collections[_collectionId] = _collection
        logger.debug(f"Created collection {_collectionId}")
        return _collectionId

    def get_collection(self, collection_id: str) -> Optional[Collection]:
        _collection = self.collections.get(collection_id)
        return _collection

    def get_collection_count(self,collection_id: str) -> int:
        return self.get_collection(collection_id).count()

    def update_data(self,collection_id: str, ids: OneOrMany[ID],
                    metadata: Optional[OneOrMany[Metadata]] = None,
                    documents: Optional[OneOrMany[Document]] = None, ) -> None:
        self.get_collection(collection_id).upsert(documents=documents, metadatas=metadata, ids=ids)
        logger.debug(f"Updated collection {collection_id}")

    def query(self,collection_id: str, query: str, count: int) -> QueryResult:
        logger.debug(f"Querying collection {collection_id} with query {query}")
        return self.get_collection(collection_id).query(
            query_texts=[query],
            n_results=count
        )

    def get(self,collection_id: str, id: list[str]) -> GetResult:
        return self.get_collection(collection_id).get(ids=id)

    def get_all_ids(self,collection_id: str) -> list[ID]:
        return self.get_collection(collection_id).get()['ids']

    def get_deleted_ids(self,collection_id: str,_cache:dict[str,Any]) -> List[str]:
        collection = self.get_collection(collection_id)
        if collection is None:
            return []

        all_ids_in_chromadb = self.get_all_ids(collection_id)
        if all_ids_in_chromadb is None:
            return []

        deleted_id = []
        for id in all_ids_in_chromadb:
            if id not in _cache:
                deleted_id.append(id)
        return deleted_id

    def delete(self,collection_id: str, ids: list[ID]) -> None:
        self.get_collection(collection_id).delete(ids=ids)
        logger.debug(f"Deleted ids {ids} from collection {collection_id}")
