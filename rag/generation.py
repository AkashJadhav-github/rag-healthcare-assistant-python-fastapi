"""
LLM generation with healthcare-specific prompt engineering.
Supports OpenAI GPT-4 and Anthropic Claude with few-shot examples.
"""

import os
import sys
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

from app.config import settings
from app.services.metrics import llm_latency

logger = structlog.get_logger()


SYSTEM_PROMPT = """You are a trusted medical knowledge assistant for healthcare professionals.
Your role is to provide accurate, evidence-based clinical information by synthesizing
retrieved medical knowledge base content.

CRITICAL RULES:
1. ONLY answer using the provided context. Do NOT hallucinate or add information not in the sources.
2. If the context does not contain sufficient information, say: "I cannot find sufficient information in the knowledge base to answer this question."
3. Always cite your sources using [Source: Document Title, Page X] notation.
4. For clinical decisions, add: "⚠️ Always verify with current clinical guidelines and consult a specialist."
5. Do NOT provide specific patient treatment recommendations — this is for educational/reference use only.
6. Use precise medical terminology appropriate for healthcare professionals.
7. Structure complex answers with clear sections.

You are NOT a replacement for clinical judgment."""


FEW_SHOT_EXAMPLES = [
    {
        "query": "What are the first-line treatments for type 2 diabetes?",
        "context": "According to ADA 2024 guidelines, metformin remains the preferred initial pharmacologic agent for type 2 diabetes management in the absence of contraindications...",
        "answer": """Based on ADA 2024 guidelines [Source: ADA Standards of Care, Page 15]:

**First-line pharmacotherapy for T2DM:**
1. **Metformin** — preferred initial agent if eGFR ≥30, no contraindications
2. **GLP-1 receptor agonists** — preferred if CVD, HF, or CKD present
3. **SGLT-2 inhibitors** — preferred in HF with reduced EF or CKD

⚠️ Always verify with current clinical guidelines and consult a specialist.""",
    }
]


class LLMGenerator:
    def __init__(self) -> None:
        self._openai_client: Any = None
        self._anthropic_client: Any = None

    def _get_openai(self) -> Any:
        if self._openai_client is None:
            from openai import AsyncOpenAI

            self._openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    def _get_anthropic(self) -> Any:
        if self._anthropic_client is None:
            import anthropic

            self._anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._anthropic_client

    def _build_context(self, sources: List[Dict[str, Any]]) -> str:
        if not sources:
            return "No relevant documents found in the knowledge base."
        parts = []
        for i, s in enumerate(sources, start=1):
            title = s.get("document_title", "Unknown")
            page = s.get("page_number", "")
            section = s.get("section", "")
            content = s.get("chunk_content", "")
            header = f"[Source {i}: {title}"
            if page:
                header += f", Page {page}"
            if section:
                header += f", Section: {section}"
            header += "]"
            parts.append(f"{header}\n{content}")
        return "\n\n---\n\n".join(parts)

    def _build_messages(self, query: str, sources: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        context = self._build_context(sources)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        for ex in FEW_SHOT_EXAMPLES:
            messages.append(
                {
                    "role": "user",
                    "content": f"Context:\n{ex['context']}\n\nQuestion: {ex['query']}",
                }
            )
            messages.append({"role": "assistant", "content": ex["answer"]})

        messages.append(
            {
                "role": "user",
                "content": f"Context from knowledge base:\n\n{context}\n\nQuestion: {query}\n\nProvide a comprehensive, cited answer.",
            }
        )
        return messages

    def _build_system_with_history(self, conversation_history: Optional[List[Dict[str, str]]] = None) -> str:
        """Return the system prompt, optionally prepending prior session exchanges."""
        if not conversation_history:
            return SYSTEM_PROMPT
        history_lines = ["Previous exchanges in this session:"]
        for exchange in conversation_history:
            history_lines.append(f"Q: {exchange['query']}")
            history_lines.append(f"A: {exchange['answer']}")
        history_section = "\n".join(history_lines)
        return f"{history_section}\n\n---\n\n{SYSTEM_PROMPT}"

    async def generate(
        self,
        query: str,
        sources: List[Dict[str, Any]],
        max_tokens: int = 1500,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        t0 = time.time()
        messages = self._build_messages(query, sources)

        # Inject conversation history into the system message if provided
        if conversation_history:
            system_with_history = self._build_system_with_history(conversation_history)
            for msg in messages:
                if msg["role"] == "system":
                    msg["content"] = system_with_history
                    break

        if settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
            answer, model_used = await self._anthropic_generate(messages, max_tokens)
        elif settings.OPENAI_API_KEY:
            answer, model_used = await self._openai_generate(messages, max_tokens)
        else:
            answer = self._fallback_answer(query, sources)
            model_used = "fallback"

        llm_latency.observe(time.time() - t0)
        confidence = self._compute_confidence(sources)

        return {
            "answer": answer,
            "model_used": model_used,
            "confidence_score": confidence,
            "latency_ms": int((time.time() - t0) * 1000),
        }

    async def generate_stream(
        self,
        query: str,
        sources: List[Dict[str, Any]],
        max_tokens: int = 1500,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream LLM response text chunk by chunk."""
        messages = self._build_messages(query, sources)

        # Inject conversation history into the system message if provided
        if conversation_history:
            system_with_history = self._build_system_with_history(conversation_history)
            for msg in messages:
                if msg["role"] == "system":
                    msg["content"] = system_with_history
                    break

        if settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
            async for chunk in self._anthropic_stream(messages, max_tokens):
                yield chunk
        elif settings.OPENAI_API_KEY:
            async for chunk in self._openai_stream(messages, max_tokens):
                yield chunk
        else:
            yield self._fallback_answer(query, sources)

    async def _openai_stream(
        self, messages: List[Dict[str, Any]], max_tokens: int
    ) -> AsyncGenerator[str, None]:
        client = self._get_openai()
        stream = await client.chat.completions.create(
            model=settings.OPENAI_LLM_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.1,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def _anthropic_stream(
        self, messages: List[Dict[str, Any]], max_tokens: int
    ) -> AsyncGenerator[str, None]:
        client = self._get_anthropic()
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_messages = [m for m in messages if m["role"] != "system"]
        async with client.messages.stream(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=user_messages,
            temperature=0.1,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def _openai_generate(self, messages: List[Dict[str, Any]], max_tokens: int) -> Tuple[str, str]:
        client = self._get_openai()
        response = await client.chat.completions.create(
            model=settings.OPENAI_LLM_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return response.choices[0].message.content, settings.OPENAI_LLM_MODEL

    async def _anthropic_generate(self, messages: List[Dict[str, Any]], max_tokens: int) -> Tuple[str, str]:
        client = self._get_anthropic()
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_messages = [m for m in messages if m["role"] != "system"]
        response = await client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=user_messages,
            temperature=0.1,
        )
        return response.content[0].text, settings.ANTHROPIC_MODEL

    def _fallback_answer(self, query: str, sources: List[Dict[str, Any]]) -> str:
        if not sources:
            return "No relevant information found in the knowledge base for your query."
        top = sources[0]
        return (
            f"Based on {top.get('document_title', 'the knowledge base')}:\n\n"
            f"{top.get('chunk_content', '')}\n\n"
            "⚠️ LLM provider not configured. Showing raw retrieved content."
        )

    def _compute_confidence(self, sources: List[Dict[str, Any]]) -> float:
        if not sources:
            return 0.0
        scores = [s.get("similarity_score", 0) for s in sources]
        avg = sum(scores) / len(scores)
        top_score = max(scores)
        return round(min((avg * 0.4 + top_score * 0.6) * 1.1, 1.0), 3)


generator = LLMGenerator()
