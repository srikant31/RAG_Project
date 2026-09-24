"""
QueryDesk - LlamaIndex-backed response synthesis and query engine.

Retrieval orchestration is handled by the LlamaIndex fusion retriever, while
response synthesis is now also delegated to a LlamaIndex RetrieverQueryEngine
using a lightweight google-genai-backed custom LLM adapter.
"""
from __future__ import annotations

from collections.abc import Generator
import json
import re

from google import genai
from google.genai import types
from llama_index.core import PromptTemplate
from llama_index.core.base.llms.types import CompletionResponse, LLMMetadata
from llama_index.core.llms.callbacks import llm_completion_callback
from llama_index.core.llms.custom import CustomLLM
from llama_index.core.query_engine import RetrieverQueryEngine
from tenacity import retry, stop_after_attempt, wait_exponential

from QueryDesk.config import settings
from QueryDesk.core.retrieval.hybrid import HybridRetriever
from QueryDesk.models.schemas import RetrievedChunk, SourceReference
from QueryDesk.utils.logger import logger

SYSTEM_PROMPT = """You are QueryDesk, an intelligent enterprise helpdesk assistant.
Your role is to answer questions accurately based ONLY on the provided enterprise documentation.

Guidelines:
- Answer clearly and concisely using the provided context
- Always cite your sources by referencing the document name and page/section
- If the answer is not in the provided context, say: "I couldn't find this in the available documentation. Please contact your support team."
- For follow-up questions, use the conversation history to maintain context
- Be professional, helpful, and precise
- Format responses with clear structure when listing steps or options
- Never make up information not present in the context
- If sources contain conflicting information, acknowledge the discrepancy and cite all conflicting sources
"""

TEXT_QA_TEMPLATE = PromptTemplate(
    """CONVERSATION HISTORY:
{chat_history}

You must answer based only on the retrieved documentation context below.
When you use information from the context, cite the supporting source in natural language.
If the answer is not supported by the context, say you could not find it in the available documentation.
If the context is ambiguous or incomplete, acknowledge the uncertainty and state what information is available.

Context:
---------------------
{context_str}
---------------------

Question: {query_str}

Answer:"""
)


class GoogleGenAILlamaLLM(CustomLLM):
    """Minimal LlamaIndex LLM adapter backed by the modern google-genai SDK."""

    model_name: str = settings.gemini_llm_model
    temperature: float = 0.2
    max_tokens: int = 1024

    def __init__(self) -> None:
        super().__init__()
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            model_name=self.model_name,
            context_window=32768,
            num_output=self.max_tokens,
            is_chat_model=False,
        )

    @llm_completion_callback()
    def complete(
        self, prompt: str, formatted: bool = False, **kwargs
    ) -> CompletionResponse:
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ),
        )
        return CompletionResponse(text=response.text or "")

    @llm_completion_callback()
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs
    ) -> Generator[CompletionResponse, None, None]:
        full_text = ""
        response = self._client.models.generate_content_stream(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ),
        )
        for chunk in response:
            delta = chunk.text or ""
            if not delta:
                continue
            full_text += delta
            yield CompletionResponse(text=full_text, delta=delta)

    @classmethod
    def class_name(cls) -> str:
        return "google_genai_llama_llm"


class RAGGenerator:
    """
    LlamaIndex-based response synthesis over QueryDesk's hybrid retriever.

    Retrieval is performed by HybridRetriever's fusion retriever. Answer
    synthesis is handled by LlamaIndex RetrieverQueryEngine with a custom
    google-genai-backed LLM adapter.
    """

    def __init__(self, retriever: HybridRetriever):
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_llm_model
        self._retriever = retriever
        self._llm = GoogleGenAILlamaLLM()
        self._last_source_chunks: list[RetrievedChunk] = []
        logger.info(f"RAGGenerator initialized with LlamaIndex query engine: {self._model}")

    def _history_to_text(self, chat_history: list[dict]) -> str:
        if not chat_history:
            return "No previous messages."
        lines = []
        for turn in chat_history[-6:]:
            role = "User" if turn["role"] == "user" else "QueryDesk"
            lines.append(f"{role}: {turn['content']}")
        return "\n".join(lines)

    def _build_query_engine(self, chat_history: list[dict], streaming: bool) -> RetrieverQueryEngine:
        return RetrieverQueryEngine.from_args(
            retriever=self._retriever.as_llama_retriever(),
            llm=self._llm,
            text_qa_template=TEXT_QA_TEMPLATE.partial_format(
                chat_history=self._history_to_text(chat_history)
            ),
            streaming=streaming,
            use_async=False,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def generate(
        self,
        query: str,
        retrieved_chunks: list[RetrievedChunk],
        chat_history: list[dict],
    ) -> tuple[str, list[SourceReference], list[str]]:
        # If no relevant chunks found, use conversational mode
        if not retrieved_chunks:
            return self._generate_conversational(query, chat_history)
        
        try:
            query_engine = self._build_query_engine(chat_history=chat_history, streaming=False)
            response = query_engine.query(query)
            answer_text = str(response)
            resolved_chunks = self._response_nodes_to_chunks(response.source_nodes) or retrieved_chunks
            sources = self._extract_sources(resolved_chunks)
            suggestions = self._generate_suggestions(query, resolved_chunks)
            logger.info(f"Generated via LlamaIndex: {len(answer_text)} chars, {len(sources)} sources")
            return answer_text, sources, suggestions
        except Exception as e:
            # Fallback to raw chunks for any LLM failure (quota, network, API errors, etc.)
            logger.warning(f"LLM generation failed, falling back to raw chunks: {e}")
            return self._generate_fallback(query, retrieved_chunks, str(e))

    def generate_stream(
        self,
        query: str,
        retrieved_chunks: list[RetrievedChunk],
        chat_history: list[dict],
    ):
        # If no relevant chunks found, use conversational mode
        if not retrieved_chunks:
            answer_text, _, _ = self._generate_conversational(query, chat_history)
            # Yield the full response at once for conversational mode
            yield answer_text
            return
        
        try:
            query_engine = self._build_query_engine(chat_history=chat_history, streaming=True)
            response = query_engine.query(query)
            # Capture source nodes from the streaming response for later use
            self._last_source_chunks = self._response_nodes_to_chunks(
                getattr(response, "source_nodes", None)
            ) or retrieved_chunks
            for chunk in response.response_gen:
                if chunk:
                    yield chunk
        except Exception as e:
            # Fallback to raw chunks for any LLM failure (quota, network, API errors, etc.)
            logger.warning(f"LLM generation failed, falling back to raw chunks: {e}")
            answer_text, sources, suggestions = self._generate_fallback(query, retrieved_chunks, str(e))
            # Yield the full response at once for fallback mode
            yield answer_text

    def resolve_sources(
        self,
        query: str,
        retrieved_chunks: list[RetrievedChunk],
        chat_history: list[dict],
    ) -> list[SourceReference]:
        """Resolve source references using the LlamaIndex retriever output."""
        resolved_chunks = retrieved_chunks or self._retriever.retrieve(query).chunks
        return self._extract_sources(resolved_chunks)

    def _response_nodes_to_chunks(self, source_nodes) -> list[RetrievedChunk]:
        chunks: list[RetrievedChunk] = []
        for source_node in source_nodes or []:
            metadata = source_node.metadata or {}
            page_number = metadata.get("page_number")
            chunks.append(
                RetrievedChunk(
                    chunk_id=metadata.get("chunk_id", source_node.node_id),
                    doc_id=metadata.get("doc_id", ""),
                    doc_name=metadata.get("doc_name", "Unknown"),
                    content=source_node.get_content(),
                    page_number=page_number if page_number not in (0, "0", None) else None,
                    dense_score=float(metadata.get("dense_score", 0.0) or 0.0),
                    sparse_score=float(metadata.get("sparse_score", 0.0) or 0.0),
                    final_score=float(source_node.score or 0.0),
                )
            )
        return chunks

    def _extract_sources(self, chunks: list[RetrievedChunk]) -> list[SourceReference]:
        import re as _re
        import html as _html
        seen = set()
        sources = []
        ranked_chunks = sorted(
            chunks,
            key=lambda chunk: chunk.final_score,
            reverse=True,
        )
        for chunk in ranked_chunks[:5]:
            key = f"{chunk.doc_name}:{chunk.page_number}"
            if key in seen:
                continue
            seen.add(key)
            # Strip tags → unescape entities → collapse whitespace → plain text only
            clean = _re.sub(r"<[^>]+>", " ", chunk.content)
            clean = _html.unescape(clean)
            clean = _re.sub(r"&[a-zA-Z]+;", " ", clean)   # catch any missed entities
            clean = _re.sub(r"\s+", " ", clean).strip()
            sources.append(
                SourceReference(
                    doc_name=chunk.doc_name,
                    chunk_content=clean[:220] + "..." if len(clean) > 220 else clean,
                    page_number=chunk.page_number,
                    relevance_score=min(chunk.final_score * 10, 1.0),
                )
            )
        return sources

    def _generate_fallback(
        self,
        query: str,
        retrieved_chunks: list[RetrievedChunk],
        error_message: str = "",
    ) -> tuple[str, list[SourceReference], list[str]]:
        """Fallback when LLM generation fails. Displays raw chunks."""
        # Extract error code and title from error message
        error_tag = ""
        if error_message:
            # Try to extract error code (e.g., "429") and title (e.g., "RESOURCE_EXHAUSTED")
            import re
            # Try multiple patterns for error code
            code_match = re.search(r"'code':\s*(\d+)", error_message) or re.search(r"Error[:\s]*(\d+)", error_message)
            title_match = re.search(r"([A-Z_]{3,})", error_message)
            
            code = code_match.group(1) if code_match else ""
            title = title_match.group(1) if title_match else ""
            
            if code and title:
                error_tag = f"`Error {code}: {title}`"
            elif code:
                error_tag = f"`Error {code}`"
            elif title:
                error_tag = f"`{title}`"
        
        error_header = (
            "**⚠️ LLM Generation Failed**\n\n"
            f"{error_tag}\n\n"
            "Showing retrieved document chunks instead of a synthesized answer.\n\n"
            "---\n\n"
            "**Retrieved Context for your question:**\n\n"
        )
        
        # Build fallback answer from chunks
        chunk_texts = []
        for i, chunk in enumerate(retrieved_chunks[:5], 1):
            chunk_texts.append(
                f"**{i}. {chunk.doc_name}** (Page {chunk.page_number}, Score: {chunk.final_score:.2f})\n\n"
                f"{chunk.content}\n\n"
            )
        
        fallback_answer = error_header + "".join(chunk_texts)
        
        # Extract sources from chunks
        sources = self._extract_sources(retrieved_chunks)
        
        # No suggestions in fallback mode
        suggestions = []
        
        return fallback_answer, sources, suggestions

    def _generate_suggestions(self, query: str, chunks: list[RetrievedChunk]) -> list[str]:
        try:
            context_snippet = " ".join([c.content[:180] for c in chunks[:3]])
            prompt = (
                "You are generating concise, useful follow-up questions for an enterprise helpdesk chat.\n"
                f"User question: {query}\n"
                f"Relevant context: {context_snippet}\n\n"
                "Return exactly 3 strong follow-up questions as a JSON array of strings.\n"
                "Rules:\n"
                "- Each item must be a complete question.\n"
                "- Each item must be specific and practical.\n"
                "- No numbering, no bullets, no explanations.\n"
                "- Avoid repeating the user's original question.\n"
                "- Keep each question under 90 characters.\n"
            )
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=220,
                    response_mime_type="application/json",
                ),
            )
            suggestions = self._normalize_suggestions(response.text or "")
            if len(suggestions) < 3:
                suggestions.extend(self._fallback_suggestions(query, chunks))
            deduped = []
            seen = set()
            for suggestion in suggestions:
                key = suggestion.lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(suggestion)
                if len(deduped) == 3:
                    break
            return deduped
        except Exception as e:
            logger.warning(f"Suggestion generation failed (non-critical): {e}")
            return self._fallback_suggestions(query, chunks)

    def _normalize_suggestions(self, raw_text: str) -> list[str]:
        candidates: list[str] = []
        try:
            json_block = raw_text
            if not raw_text.strip().startswith("["):
                match = re.search(r"\[[\s\S]*\]", raw_text)
                if match:
                    json_block = match.group(0)
            parsed = json.loads(json_block)
            if isinstance(parsed, list):
                candidates = [str(item) for item in parsed]
        except Exception:
            candidates = raw_text.splitlines()

        cleaned: list[str] = []
        for item in candidates:
            suggestion = re.sub(r"^\s*[-*\d.)\s]+", "", item).strip().strip('"').strip("'")
            if not suggestion:
                continue
            if len(suggestion) < 18:
                continue
            lower = suggestion.lower()
            if any(
                blocked in lower
                for blocked in ["json", "requested", "follow-up questions", "here is"]
            ):
                continue
            if suggestion[-1] not in {"?", "."}:
                suggestion += "?"
            if suggestion.endswith("."):
                suggestion = suggestion[:-1] + "?"
            cleaned.append(suggestion)
        return cleaned

    def _fallback_suggestions(self, query: str, chunks: list[RetrievedChunk]) -> list[str]:
        doc_hint = chunks[0].doc_name.replace(".md", "").replace("_", " ") if chunks else "this topic"
        return [
            "What steps should I follow if I need an exception?",
            f"Who approves exceptions or edge cases in {doc_hint}?",
            "Where is the full policy documented in more detail?",
        ]

    def _generate_conversational(self, query: str, chat_history: list[dict]) -> tuple[str, list[SourceReference], list[str]]:
        """Handle conversational queries when no relevant documents are found."""
        conversational_prompt = (
            "You are QueryDesk, a helpful enterprise helpdesk assistant. "
            "The user has asked a question that doesn't match any documentation. "
            "Respond naturally and helpfully. If it's a greeting, respond warmly. "
            "If it's unclear what they want, ask clarifying questions about documentation topics. "
            f"User query: {query}"
        )
        
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=conversational_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=2048,
                ),
            )
            answer_text = response.text or "I couldn't find relevant documentation for that. Could you ask about a specific policy or procedure?"
        except Exception as e:
            logger.warning(f"Conversational generation failed: {e}")
            answer_text = "I couldn't find relevant documentation for that. Could you ask about a specific policy or procedure?"
        
        # Generate generic suggestions for documentation topics
        suggestions = [
            "What are the company policies?",
            "How do I request leave?",
            "What's the remote work policy?",
        ]
        
        logger.info(f"Generated conversational response: {len(answer_text)} chars")
        return answer_text, [], suggestions