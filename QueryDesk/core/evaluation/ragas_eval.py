"""
QueryDesk — RAGAS Evaluation Engine
Asynchronously scores RAG answers for quality tracking.
Metrics: Faithfulness, Answer Relevancy, Context Precision
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import nest_asyncio

from QueryDesk.config import settings
from QueryDesk.models.schemas import RAGASScore, RetrievedChunk
from QueryDesk.utils.logger import logger

SCORES_PATH = Path("data/ragas_scores.json")

# Apply nest_asyncio globally to handle Streamlit's threading
nest_asyncio.apply()


class RAGASEvaluator:
    """
    Evaluates RAG answer quality using RAGAS metrics.
    Scores are stored for dashboard analytics.

    Note: Full RAGAS requires datasets package. We implement
    a lightweight scoring proxy using Gemini when RAGAS is unavailable,
    and full RAGAS when available.
    """

    def __init__(self):
        self._scores_log: list[dict] = self._load_scores()
        self._enabled = settings.ragas_enabled
        if self._enabled:
            logger.info("RAGASEvaluator initialized — evaluation enabled")
        else:
            logger.info("RAGASEvaluator initialized — evaluation DISABLED")

    def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[RetrievedChunk],
        session_id: str,
        message_id: str,
    ) -> Optional[RAGASScore]:
        """
        Evaluate answer quality.

        Args:
            question: Original user question
            answer: Generated answer
            contexts: Retrieved chunks used as context
            session_id: Session identifier for logging
            message_id: Message identifier for logging

        Returns:
            RAGASScore or None if evaluation is disabled/fails
        """
        if not self._enabled:
            return None

        try:
            score = self._compute_scores(question, answer, contexts)
            self._log_score(score, question, session_id, message_id)
            logger.info(
                f"RAGAS scores — faithfulness={score.faithfulness:.2f}, "
                f"relevancy={score.answer_relevancy:.2f}, "
                f"overall={score.overall:.2f}"
            )
            return score
        except Exception as e:
            logger.warning(f"RAGAS evaluation failed (non-critical): {e}")
            return None

    def _compute_scores(
        self,
        question: str,
        answer: str,
        contexts: list[RetrievedChunk],
    ) -> RAGASScore:
        # If Gemini RAGAS is disabled, use heuristic evaluation only
        if not settings.ragas_gemini_enabled:
            logger.info("Gemini RAGAS disabled, using heuristic evaluation")
            return self._heuristic_eval(question, answer, contexts)
        
        try:
            return self._full_ragas_eval(question, answer, contexts)
        except Exception as e:
            logger.warning(f"Full RAGAS eval failed, falling back to Gemini judge: {e}")
            try:
                return self._gemini_judge_eval(question, answer, contexts)
            except Exception as e2:
                logger.warning(f"Gemini judge eval failed, falling back to heuristic: {e2}")
                return self._heuristic_eval(question, answer, contexts)

    def _gemini_judge_eval(
        self,
        question: str,
        answer: str,
        contexts: list[RetrievedChunk],
    ) -> RAGASScore:
        """Uses Gemini 3 Flash to score the answer's quality."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        context_text = "\n".join([c.content for c in contexts[:3]])

        prompt = f"""You are a RAG evaluation judge. Rate the following answer based on the context and question.

QUESTION: {question}
CONTEXT: {context_text}
ANSWER: {answer}

Provide exactly three scores between 0.0 and 1.0 (where 1.0 is perfect):
1. Faithfulness: Is the answer derived ONLY from the provided context without halluncinations?
2. Answer Relevancy: Does the answer directly and completely address the user's question?
3. Context Precision: How relevant is the provided context to the question?

Return ONLY a JSON object like this:
{{"faithfulness": 0.9, "answer_relevancy": 1.0, "context_precision": 0.8}}
"""
        response = client.models.generate_content(
            model=settings.gemini_llm_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )

        try:
            data = json.loads(response.text)
            return RAGASScore(
                faithfulness=float(data.get("faithfulness", 0.0)),
                answer_relevancy=float(data.get("answer_relevancy", 0.0)),
                context_precision=float(data.get("context_precision", 0.0)),
            )
        except Exception:
            raise ValueError("Failed to parse judge response")

    def _full_ragas_eval(
        self,
        question: str,
        answer: str,
        contexts: list[RetrievedChunk],
    ) -> RAGASScore:
        """Full RAGAS evaluation using ragas library with Gemini as judge."""
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
        from datasets import Dataset

        llm = LangchainLLMWrapper(
            ChatGoogleGenerativeAI(
                model=settings.gemini_llm_model,
                google_api_key=settings.gemini_api_key,
                temperature=0.0,
            )
        )
        embeddings = LangchainEmbeddingsWrapper(
            GoogleGenerativeAIEmbeddings(
                model=settings.gemini_embedding_model,
                google_api_key=settings.gemini_api_key,
                max_retries=0,  # Disable retries for faster fallback
            )
        )

        context_texts = [c.content for c in contexts[:4]]
        dataset = Dataset.from_dict({
            "question": [question],
            "answer": [answer],
            "contexts": [context_texts],
        })

        # Run evaluation in a separate thread with its own event loop
        import concurrent.futures
        from google.api_core.exceptions import ResourceExhausted
        
        def run_in_separate_thread():
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            nest_asyncio.apply(loop)
            # evaluate() is synchronous (returns EvaluationResult directly)
            return evaluate(
                dataset,
                metrics=[faithfulness, answer_relevancy],
                llm=llm,
                embeddings=embeddings,
                raise_exceptions=False,
                show_progress=False,
            )
        
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_separate_thread)
                # Set a very short timeout (2 seconds) to force fallback on quota errors
                result = future.result(timeout=2)
        except (ResourceExhausted, concurrent.futures.TimeoutError, Exception) as e:
            # Immediately fall back on any error including quota errors or timeout
            raise ResourceExhausted(f"Gemini quota exceeded or error: {str(e)}, falling back")
        scores_df = result.to_pandas()
        row = scores_df.iloc[0]

        return RAGASScore(
            faithfulness=round(float(row.get("faithfulness") or 0), 3),
            answer_relevancy=round(float(row.get("answer_relevancy") or 0), 3),
            context_precision=round(float(row.get("context_precision") or 0), 3),
        )

    def _heuristic_eval(
        self,
        question: str,
        answer: str,
        contexts: list[RetrievedChunk],
    ) -> RAGASScore:
        """Lightweight heuristic scoring proxy."""
        # Faithfulness: does answer use words from context?
        context_words = set(
            " ".join(c.content for c in contexts).lower().split()
        )
        answer_words = set(answer.lower().split())
        overlap = len(answer_words & context_words)
        faithfulness = min(overlap / max(len(answer_words), 1), 1.0)

        # Relevancy: does answer address the question?
        question_words = set(question.lower().split())
        rel_overlap = len(answer_words & question_words)
        relevancy = min(rel_overlap / max(len(question_words), 1), 1.0)

        # Context precision: average retrieval scores
        if contexts:
            precision = sum(c.final_score for c in contexts) / len(contexts)
            precision = min(precision * 10, 1.0)
        else:
            precision = 0.0

        return RAGASScore(
            faithfulness=round(faithfulness, 3),
            answer_relevancy=round(relevancy, 3),
            context_precision=round(precision, 3),
        )

    def _log_score(
        self,
        score: RAGASScore,
        question: str,
        session_id: str,
        message_id: str,
    ) -> None:
        """Append score to the scores log file."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "message_id": message_id,
            "question": question[:200],
            "faithfulness": score.faithfulness,
            "answer_relevancy": score.answer_relevancy,
            "context_precision": score.context_precision,
            "overall": score.overall,
        }
        self._scores_log.append(entry)
        self._save_scores()

    def get_analytics(self) -> dict:
        """Return aggregated analytics from all scored responses."""
        from QueryDesk.models.schemas import AnalyticsSummary
        if not self._scores_log:
            summary = AnalyticsSummary()
            return summary.model_dump()

        total = len(self._scores_log)
        avg_faith = sum(s.get("faithfulness", 0) for s in self._scores_log) / total
        avg_rel = sum(s.get("answer_relevancy", 0) for s in self._scores_log) / total
        avg_prec = sum(s.get("context_precision", 0) for s in self._scores_log) / total
        avg_overall = sum(s.get("overall", 0) for s in self._scores_log) / total

        gaps = [
            s["question"]
            for s in self._scores_log
            if s.get("overall", 1.0) < 0.4
        ][-10:]

        summary = AnalyticsSummary(
            total_queries=total,
            total_evaluations=total,
            avg_faithfulness=round(avg_faith, 3),
            avg_relevancy=round(avg_rel, 3),
            avg_precision=round(avg_prec, 3),
            avg_overall=round(avg_overall, 3),
            knowledge_gaps=gaps,
        )
        return summary.model_dump()

    def _save_scores(self) -> None:
        SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SCORES_PATH, "w", encoding="utf-8") as f:
            json.dump(self._scores_log, f, indent=2)

    def _load_scores(self) -> list[dict]:
        if SCORES_PATH.exists():
            try:
                with open(SCORES_PATH, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []
