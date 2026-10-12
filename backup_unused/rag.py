import os
import re
import time
from pathlib import Path
from typing import Callable, TypeVar, TypedDict
from uuid import NAMESPACE_URL, uuid5
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException
from pypdf import PdfReader


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
COLLECTION_NAME = "agent_documents"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SUPPORTED_SUFFIXES = {".md", ".pdf", ".txt"}
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
UPLOAD_BATCH_SIZE = 32
MAX_WRITE_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
_T = TypeVar("_T")
RAG_SYSTEM_PROMPT = """You are a voice AI assistant connected to a RAG (Retrieval-Augmented Generation) knowledge base.

Your job is to answer the user's question using the retrieved RAG context.

VOICE RESPONSE RULES:
1. Give a concise, direct answer that is comfortable to hear aloud. For simple questions, use about 30–50 words or less when fewer words fully answer the question. For normal questions, target 40–80 words in 2–5 sentences. Keep detailed answers to about 120 words unless the user explicitly asks for a complete or detailed explanation.
2. Give the most relevant information first. Do not repeat the question, add an unnecessary introduction or "In short" summary, or include extra benefits, examples, or explanations unless asked.
3. Use natural spoken English and short paragraphs. Avoid Markdown tables, headings, large bullet lists, code blocks, and excessive punctuation. Combine related points into a few clear sentences.
4. Use the retrieved context as the primary source of truth, even when it contains more detail than the answer needs. Select only the facts relevant to the user's question; do not omit or alter retrieved context itself.
5. Do not mention "RAG", "retrieved context", "chunks", "vector database", or internal tools, except in the required unavailable-information response.
6. Expand beyond about 120 words only when the user explicitly asks for detail, a complete explanation, or all available information; keep the response suitable for speech.
7. If the retrieved context does not contain the requested fact, reply exactly: "That information is not available in the knowledge base." Never guess.
8. Keep names, company names, technical terms, and important facts accurate.
9. Do not start every response with phrases like "According to the information..." or "Based on the context...".
10. Answer immediately without unnecessary introduction.

EXAMPLE:

User: "What about GenLab?"

Retrieved context:
"GenLab is an AI-focused company headquartered in Nagercoil and Bengaluru. It has three verticals: Brand Studio, AI Forge, and Launchpad..."

Good voice response:
"GenLab is an AI-focused company headquartered in Nagercoil and Bengaluru. It combines AI with creative and product development through Brand Studio, AI Forge, and Launchpad."

Bad response:
"GenLab is an AI-focused company headquartered in Nagercoil and Bengaluru. It offers three main verticals: Brand Studio, AI Forge, and Launchpad. Brand Studio focuses on branding, content, and design..."

The bad response is too long for a voice assistant.

IMPORTANT:
Prioritize brevity, clarity, accuracy, and natural speech.
The default answer should be SHORT.
Only expand the answer when the user explicitly asks for more information."""
NOT_AVAILABLE_ANSWER = "That information is not available in the knowledge base."
_FOUNDER_QUESTION = re.compile(
    r"\bwho\s+(?:is|are|was|were)\s+(?:the\s+)?(?:co[- ]?founder|founder)s?\b"
    r"|\bwho\s+(?:co[- ]?founded|founded|started)\s+GenLab\b"
    r"|\b(?:co[- ]?founder|founder)s?\s+of\s+GenLab\b"
    r"|\bwho\s+are\s+GenLab['\u2019]s\s+(?:co[- ]?founders|founders)\b",
    re.IGNORECASE,
)
_FOUNDER_EVIDENCE = re.compile(
    r"\b(?:co[- ]?founder|founder)(?:s)?(?:\s+of\s+GenLab)?\s*"
    r"(?:is|was|:|[-\u2013\u2014])\s+[A-Z][\w'-]+"
    r"|\b[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+){0,2}\s+"
    r"(?:is|was)\s+(?:the\s+)?(?:co[- ]?founder|founder)\s+of\s+GenLab\b"
    r"|\bGenLab\s+(?:was\s+)?(?:co[- ]?founded|founded)\s+by\s+[A-Z][\w'-]+",
    re.IGNORECASE,
)


class RetrievedDocument(TypedDict):
    source: str
    document: str
    chunk_id: str
    score: float | None


def rag_debug_log(message: str) -> None:
    if os.getenv("RAG_DEBUG", "").strip().lower() in {"1", "true", "yes"}:
        safe_message = message.encode("ascii", errors="backslashreplace").decode("ascii")
        print(f"[RAG] {safe_message}", flush=True)


def build_context(results: list[RetrievedDocument]) -> str:
    """Format retrieved chunks with explicit source boundaries."""
    return "\n\n".join(
        f"[Source {index}: {result['source']}; chunk_id={result['chunk_id']}; "
        f"score={result['score'] if result['score'] is not None else 'unavailable'}]\n"
        f"{result['document']}"
        for index, result in enumerate(results, start=1)
        if result.get("document", "").strip()
    )


def generate_answer(
    client,
    model: str,
    query: str,
    context: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Generate a concise answer grounded in retrieved context."""
    if not context.strip():
        rag_debug_log(f"Final answer: {NOT_AVAILABLE_ANSWER}")
        return NOT_AVAILABLE_ANSWER

    if _FOUNDER_QUESTION.search(query) and not _FOUNDER_EVIDENCE.search(context):
        rag_debug_log(
            "Founder identity was requested, but the retrieved context does not "
            "explicitly identify a GenLab founder."
        )
        rag_debug_log(f"Final answer: {NOT_AVAILABLE_ANSWER}")
        return NOT_AVAILABLE_ANSWER

    rag_debug_log(f"Final question passed to answer model: {query}")
    rag_debug_log(
        "GenLab text present in context passed to answer model: "
        f"{'genlab' in context.casefold()}"
    )
    rag_debug_log(f"Final context passed to answer model:\n{context}")
    conversation = [{"role": "system", "content": RAG_SYSTEM_PROMPT}]
    if history:
        conversation.extend(
            message
            for message in history[-10:]
            if message.get("role") in {"user", "assistant"}
        )
    conversation.append(
        {
            "role": "user",
            "content": f"Question:\n{query}\n\nRetrieved context:\n{context}",
        }
    )
    response = client.chat.completions.create(
        model=model,
        messages=conversation,
        temperature=0.2,
    )
    answer = response.choices[0].message.content
    final_answer = (
        answer.strip()
        if answer
        else "I couldn't generate an answer from the available context."
    )
    rag_debug_log(f"Final answer: {final_answer}")
    return final_answer


class KnowledgeBase:
    def __init__(self, url: str, api_key: str) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        parsed_url = urlsplit(url.rstrip("/"))
        if parsed_url.scheme != "https":
            raise ValueError("QDRANT_URL must use HTTPS for Qdrant Cloud.")
        if parsed_url.port is None:
            url = urlunsplit(
                (parsed_url.scheme, f"{parsed_url.netloc}:6333", parsed_url.path, parsed_url.query, parsed_url.fragment)
            )
        self.client = QdrantClient(url=url, api_key=api_key)
        self._embedding_model: TextEmbedding | None = None

    @property
    def embedding_model(self) -> TextEmbedding:
        if self._embedding_model is None:
            self._embedding_model = TextEmbedding(model_name=EMBEDDING_MODEL)
        return self._embedding_model

    @staticmethod
    def _is_transient_qdrant_error(error: Exception) -> bool:
        source = error.source if isinstance(error, ResponseHandlingException) else error
        return isinstance(
            source,
            (httpx.TransportError, TimeoutError, ConnectionError, OSError),
        )

    def _with_qdrant_retries(
        self, operation: Callable[[], _T], operation_name: str
    ) -> _T:
        for attempt in range(MAX_WRITE_RETRIES + 1):
            try:
                return operation()
            except (ResponseHandlingException, httpx.TransportError, TimeoutError, ConnectionError, OSError) as error:
                if not self._is_transient_qdrant_error(error) or attempt == MAX_WRITE_RETRIES:
                    raise
                delay = RETRY_BACKOFF_SECONDS * (2**attempt)
                print(
                    f"Temporary Qdrant Cloud failure during {operation_name}; "
                    f"retrying in {delay:g}s ({attempt + 1}/{MAX_WRITE_RETRIES}).",
                    flush=True,
                )
                time.sleep(delay)
        raise RuntimeError(f"Qdrant Cloud {operation_name} did not complete.")

    def index_documents(
        self, progress_callback: Callable[[str], None] | None = None
    ) -> int:
        def log(message: str) -> None:
            print(message, flush=True)
            if progress_callback:
                progress_callback(message)

        log("Connecting to Qdrant Cloud...")
        try:
            collection_exists = self._with_qdrant_retries(
                lambda: self.client.collection_exists(COLLECTION_NAME),
                "collection check",
            )
        except Exception as error:
            raise ConnectionError(
                "Unable to connect to Qdrant Cloud. Please check QDRANT_URL and QDRANT_API_KEY."
            ) from error

        log(f"Collection: {COLLECTION_NAME}")
        points_before = 0
        if collection_exists:
            try:
                collection_info = self._with_qdrant_retries(
                    lambda: self.client.get_collection(COLLECTION_NAME),
                    "collection inspection",
                )
            except Exception as error:
                raise ConnectionError(
                    "Unable to connect to Qdrant Cloud. Please check QDRANT_URL and QDRANT_API_KEY."
                ) from error
            points_before = collection_info.points_count or 0
        log(f"Qdrant Cloud points before indexing: {points_before}")

        files = sorted(
            path
            for path in DATA_DIR.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )
        if not files:
            log("No documents found. Add .txt, .md, or .pdf files to the data folder.")
            return 0

        indexed_chunks = 0
        for path in files:
            source = path.relative_to(DATA_DIR).as_posix()
            log(f"Found document:\n{path.name}")
            try:
                if path.suffix.lower() == ".pdf":
                    reader = PdfReader(path)
                    page_count = len(reader.pages)
                    text = "\n".join(page.extract_text() or "" for page in reader.pages)
                    log(f"Pages: {page_count}")
                else:
                    text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as error:
                raise RuntimeError(f"Could not extract text from {path.name}.") from error

            log(f"Characters extracted: {len(text)}")
            chunks = self._chunk_text(text)
            if not chunks:
                raise ValueError(f"No text chunks could be created from {path.name}.")
            log(f"Chunks created: {len(chunks)}")

            embeddings = [embedding.tolist() for embedding in self.embedding_model.embed(chunks)]
            if len(embeddings) != len(chunks):
                raise RuntimeError(
                    f"Embedding count mismatch for {path.name}: "
                    f"{len(embeddings)} embeddings for {len(chunks)} chunks."
                )
            vector_size = len(embeddings[0])
            log(f"Embeddings generated: {len(embeddings)}")
            collection_size = self._ensure_collection(vector_size)
            log(f"Embedding dimension: {vector_size}")
            log(f"Collection vector dimension: {collection_size} (matches)")

            expected_ids = {
                str(uuid5(NAMESPACE_URL, f"{source}:{chunk_index}"))
                for chunk_index in range(len(chunks))
            }
            points = [
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, f"{source}:{chunk_index}")),
                    vector=embedding,
                    payload={"source": source, "document": chunk},
                )
                for chunk_index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
            ]

            log("Uploading vectors:")
            for start in range(0, len(points), UPLOAD_BATCH_SIZE):
                batch = points[start : start + UPLOAD_BATCH_SIZE]
                end = start + len(batch)
                self._with_qdrant_retries(
                    lambda batch=batch: self.client.upsert(
                        collection_name=COLLECTION_NAME,
                        points=batch,
                        wait=True,
                    ),
                    f"upload batch {start + 1}-{end}",
                )
                log(f"{end}/{len(points)}")

            self._remove_stale_source_points(source, expected_ids)
            indexed_chunks += len(chunks)

        try:
            retrieval_results = self.retrieve_documents(
                "What about GenLab?", limit=max(10, UPLOAD_BATCH_SIZE)
            )
            verified = any(
                result["source"] == "GenLab_Complete_Corpus.pdf"
                and "genlab" in result["document"].casefold()
                for result in retrieval_results
            )
        except Exception as error:
            raise RuntimeError(
                "Index upload completed, but the automatic GenLab retrieval check failed."
            ) from error
        if not verified:
            returned_sources = sorted({result["source"] for result in retrieval_results})
            raise RuntimeError(
                "Index upload completed, but retrieval did not return GenLab information "
                f"from GenLab_Complete_Corpus.pdf. Sources returned: {returned_sources or 'none'}."
            )

        try:
            points_after = self._with_qdrant_retries(
                lambda: self.client.get_collection(COLLECTION_NAME).points_count or 0,
                "final point-count check",
            )
        except Exception as error:
            raise ConnectionError(
                "Index upload and retrieval verification succeeded, but the final Qdrant Cloud "
                "point count could not be read."
            ) from error
        log("Indexing completed successfully.")
        log(
            'Retrieval verified: "What about GenLab?" returned '
            "GenLab_Complete_Corpus.pdf with GenLab text."
        )
        log(f"Qdrant Cloud points: {points_after}")
        return indexed_chunks

    def _remove_stale_source_points(
        self, source: str, expected_ids: set[str]
    ) -> None:
        scroll_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="source", match=models.MatchValue(value=source)
                )
            ]
        )
        offset = None
        stale_ids = []
        while True:
            points, offset = self._with_qdrant_retries(
                lambda offset=offset: self.client.scroll(
                    collection_name=COLLECTION_NAME,
                    scroll_filter=scroll_filter,
                    limit=UPLOAD_BATCH_SIZE,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                ),
                "source point scan",
            )
            stale_ids.extend(
                point.id
                for point in points
                if str(point.id) not in expected_ids
            )
            if offset is None:
                break

        for start in range(0, len(stale_ids), UPLOAD_BATCH_SIZE):
            batch = stale_ids[start : start + UPLOAD_BATCH_SIZE]
            self._with_qdrant_retries(
                lambda batch=batch: self.client.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=models.PointIdsList(points=batch),
                    wait=True,
                ),
                f"stale-point cleanup batch {start + 1}",
            )

    def retrieve_documents(self, query: str, limit: int = 5) -> list[RetrievedDocument]:
        if not self.client.collection_exists(COLLECTION_NAME):
            rag_debug_log(f"Collection {COLLECTION_NAME!r} does not exist; retrieved 0 chunks.")
            return []

        query_embedding = next(self.embedding_model.query_embed(query)).tolist()
        results = self.client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_embedding,
            limit=limit,
        ).points
        documents: list[RetrievedDocument] = []
        for result in results:
            payload = result.payload or {}
            document = payload.get("document", "")
            if document.strip():
                documents.append(
                    {
                        "source": str(payload.get("source", "unknown")),
                        "document": document,
                        "chunk_id": str(result.id),
                        "score": result.score,
                    }
                )
        rag_debug_log(f"Retrieval query: {query}")
        rag_debug_log(f"Retrieved chunks: {len(documents)} (limit={limit})")
        for document in documents:
            rag_debug_log(
                f"chunk_id={document['chunk_id']} score={document['score']} "
                f"source={document['source']}\n{document['document']}"
            )
        return documents

    def search(self, query: str, limit: int = 5) -> str:
        """Return formatted search results for compatibility with existing callers."""
        documents = self.retrieve_documents(query, limit)
        if not documents:
            return NOT_AVAILABLE_ANSWER
        return build_context(documents)

    def _ensure_collection(self, vector_size: int) -> int:
        if not self._with_qdrant_retries(
            lambda: self.client.collection_exists(COLLECTION_NAME),
            "collection check",
        ):
            self._with_qdrant_retries(
                lambda: self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                ),
                "collection creation",
            )
        collection_info = self._with_qdrant_retries(
            lambda: self.client.get_collection(COLLECTION_NAME),
            "collection inspection",
        )
        vectors = collection_info.config.params.vectors
        if hasattr(vectors, "size"):
            collection_size = vectors.size
        elif isinstance(vectors, dict) and vectors:
            sizes = {vector.size for vector in vectors.values()}
            if len(sizes) != 1:
                raise ValueError(
                    f"Collection {COLLECTION_NAME} has inconsistent named-vector dimensions."
                )
            collection_size = sizes.pop()
        else:
            raise ValueError(
                f"Collection {COLLECTION_NAME} does not have a compatible default vector."
            )
        if collection_size != vector_size:
            raise ValueError(
                f"Embedding dimension {vector_size} does not match "
                f"Qdrant collection dimension {collection_size}."
            )
        payload_schema = collection_info.payload_schema or {}
        if "source" not in payload_schema:
            self._with_qdrant_retries(
                lambda: self.client.create_payload_index(
                    collection_name=COLLECTION_NAME,
                    field_name="source",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                ),
                "source index creation",
            )
        return collection_size

    @staticmethod
    def _read_document(path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        text = " ".join(text.split())
        if not text:
            return []

        chunks = []
        start = 0
        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start, end)
                if boundary > start:
                    end = boundary
            chunks.append(text[start:end].strip())
            if end == len(text):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
        return chunks