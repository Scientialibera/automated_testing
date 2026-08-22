"""Azure AI Search helper retained for the evaluation notebooks.

The public ``Config`` / ``AzureSearch`` names and ``vector_search`` signature are
kept compatible with the historical notebooks while the implementation uses
current Azure Search and Azure OpenAI SDK APIs.
"""

from __future__ import annotations

import os

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.models import QueryType, VectorizedQuery
from dotenv import load_dotenv
from openai import AzureOpenAI


class Config:
    def __init__(self, path: str = ".env") -> None:
        load_dotenv(dotenv_path=path, override=False)
        self.endpoint = os.getenv("AZURE_SEARCH_ENDPOINT") or os.getenv("COG_ENDPOINT")
        self.vector_field = os.getenv("AZURE_SEARCH_VECTOR_FIELD") or os.getenv("VECTOR_FIELD_NAME")
        self.index_name = os.getenv("AZURE_SEARCH_INDEX") or os.getenv("INDEX_NAME")
        self.top_k = int(os.getenv("AZURE_SEARCH_TOP_K") or os.getenv("TOP_K") or "3")
        self.open_ai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("OPENAI_ENDPOINT") or os.getenv("OPENAI_API_BASE")
        self.engine = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or os.getenv("EMBEDDING")
        self.gpt = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT") or os.getenv("GPT")
        self.openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("OPENAI_API_VERSION") or "2024-10-21"

        required = {
            "AZURE_SEARCH_ENDPOINT": self.endpoint,
            "AZURE_SEARCH_VECTOR_FIELD": self.vector_field,
            "AZURE_SEARCH_INDEX": self.index_name,
            "AZURE_OPENAI_ENDPOINT": self.open_ai_endpoint,
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": self.engine,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")


class AzureSearch:
    def __init__(self, config: Config, index_name: str | None = None) -> None:
        self.endpoint = config.endpoint
        self.engine = config.engine
        self.index_name = index_name or config.index_name
        self.vector_field = config.vector_field
        self._credential = DefaultAzureCredential()
        self.search_client = SearchClient(
            endpoint=self.endpoint,
            index_name=self.index_name,
            credential=self._credential,
        )
        token_provider = get_bearer_token_provider(
            self._credential,
            "https://cognitiveservices.azure.com/.default",
        )
        self.openai_client = AzureOpenAI(
            azure_endpoint=config.open_ai_endpoint,
            api_version=config.openai_api_version,
            azure_ad_token_provider=token_provider,
        )

    def generate_embeddings(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("text must not be empty")
        response = self.openai_client.embeddings.create(
            model=self.engine,
            input=text.strip(),
        )
        return list(response.data[0].embedding)

    def vector_search(
        self,
        query: str,
        filter: str | None,
        k: int = 5,
        select_fields=None,
        vector_search: bool = True,
        semantic_search: bool = False,
    ):
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if k < 1:
            raise ValueError("k must be >= 1")

        selected = None
        if isinstance(select_fields, str) and select_fields != "*":
            selected = [field.strip() for field in select_fields.split(",") if field.strip()]
        elif select_fields not in (None, "*"):
            selected = list(select_fields)

        vector_queries = None
        if vector_search:
            vector_queries = [
                VectorizedQuery(
                    vector=self.generate_embeddings(query),
                    k_nearest_neighbors=k,
                    fields=self.vector_field,
                    kind="vector",
                )
            ]

        kwargs = {
            "search_text": query,
            "filter": filter or None,
            "top": k,
            "select": selected,
            "vector_queries": vector_queries,
        }
        if semantic_search:
            kwargs.update(
                {
                    "query_type": QueryType.SEMANTIC,
                    "semantic_configuration_name": "default",
                    "semantic_query": query,
                }
            )
        return self.search_client.search(**kwargs)

    def close(self) -> None:
        self.search_client.close()
        self.openai_client.close()
        self._credential.close()
