# rag.py
import os
import re
import json
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional

import numpy as np
from sentence_transformers import SentenceTransformer


@dataclass
class Chunk:
    text: str
    source: str
    chunk_id: int
    heading: str = ""


def _now() -> float:
    return time.time()


class RAGIndex:
    """
    Full local RAG index:
      - Loads markdown from knowledge_dir
      - Cleans + chunks by headings/paragraphs
      - Embeds chunks
      - Retrieves top-k with MMR (diverse context)
      - Stores cache to JSON
    """

    def __init__(
        self,
        knowledge_dir: str,
        cache_path: str = "rag_index.json",
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        max_chars: int = 700,
        overlap: int = 90,
    ):
        self.knowledge_dir = knowledge_dir
        self.cache_path = cache_path
        self.model_name = model_name
        self.max_chars = max_chars
        self.overlap = overlap

        self.embedder = SentenceTransformer(model_name)
        self.chunks: List[Chunk] = []
        self.embeddings: Optional[np.ndarray] = None
        self.meta: Dict[str, Any] = {}

    # -----------------------------
    # IO
    # -----------------------------
    def _read_md_files(self) -> List[Tuple[str, str]]:
        if not os.path.isdir(self.knowledge_dir):
            raise RuntimeError(f"knowledge_dir not found: {self.knowledge_dir}")

        items = []
        for fn in sorted(os.listdir(self.knowledge_dir)):
            if fn.lower().endswith(".md"):
                path = os.path.join(self.knowledge_dir, fn)
                with open(path, "r", encoding="utf-8") as f:
                    items.append((fn, f.read()))
        return items

    @staticmethod
    def _strip_front_matter(text: str) -> str:
        # remove optional --- yaml --- at top
        if text.lstrip().startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                return parts[2]
        return text

    @staticmethod
    def _clean(text: str) -> str:
        text = text.replace("\r", "")
        text = RAGIndex._strip_front_matter(text)

        # Remove super noisy repeated spaces
        text = re.sub(r"[ \t]+", " ", text)

        # Normalize newlines
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Remove extremely short menu-like lines (heuristic)
        lines = []
        for ln in text.split("\n"):
            s = ln.strip()
            if not s:
                lines.append("")
                continue
            # drop lines that are basically buttons/CTA
            if len(s) <= 2:
                continue
            if s.lower() in {"last ned", "les mer", "trykk her", "open", "more"}:
                continue
            lines.append(ln)
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # -----------------------------
    # Chunking
    # -----------------------------
    def _split_by_headings(self, text: str) -> List[Tuple[str, str]]:
        """
        Splits markdown into sections by headings (#, ##, ###).
        Returns list of (heading, section_text).
        """
        text = self._clean(text)
        if not text:
            return []

        blocks = []
        cur_heading = ""
        cur = []

        for ln in text.split("\n"):
            h = re.match(r"^(#{1,4})\s+(.*)$", ln.strip())
            if h:
                # flush previous
                if cur:
                    blocks.append((cur_heading, "\n".join(cur).strip()))
                cur_heading = h.group(2).strip()
                cur = [ln]
            else:
                cur.append(ln)

        if cur:
            blocks.append((cur_heading, "\n".join(cur).strip()))
        return blocks

    def _chunk_section(self, section_text: str, source: str, heading: str, start_cid: int) -> Tuple[List[Chunk], int]:
        """
        Chunk a section by paragraphs with overlap.
        """
        paras = [p.strip() for p in section_text.split("\n\n") if p.strip()]
        chunks: List[Chunk] = []
        cur = ""
        cid = start_cid

        def push(txt: str):
            nonlocal cid
            txt = txt.strip()
            if len(txt) < 80:
                return
            chunks.append(Chunk(text=txt, source=source, chunk_id=cid, heading=heading))
            cid += 1

        for p in paras:
            if len(cur) + len(p) + 2 <= self.max_chars:
                cur = (cur + "\n\n" + p).strip() if cur else p
            else:
                if cur:
                    push(cur)
                tail = cur[-self.overlap:] if cur else ""
                cur = (tail + "\n\n" + p).strip() if tail else p

                while len(cur) > self.max_chars:
                    push(cur[: self.max_chars])
                    cur = cur[self.max_chars - self.overlap :].strip()

        if cur:
            push(cur)

        return chunks, cid

    def build(self) -> Dict[str, Any]:
        t0 = _now()
        files = self._read_md_files()

        all_chunks: List[Chunk] = []
        cid = 0
        for fn, content in files:
            sections = self._split_by_headings(content)
            if not sections:
                # fallback: treat whole file as one section
                sections = [("", self._clean(content))]

            for heading, section_text in sections:
                new_chunks, cid = self._chunk_section(section_text, source=fn, heading=heading, start_cid=cid)
                all_chunks.extend(new_chunks)

        if not all_chunks:
            raise RuntimeError(f"No usable chunks created from {self.knowledge_dir}")

        texts = [c.text for c in all_chunks]
        embs = self.embedder.encode(texts, normalize_embeddings=True, show_progress_bar=True)
        embs = np.asarray(embs, dtype=np.float32)

        self.chunks = all_chunks
        self.embeddings = embs

        self.meta = {
            "model_name": self.model_name,
            "knowledge_dir": os.path.abspath(self.knowledge_dir),
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "chunks": len(self.chunks),
            "seconds": round(_now() - t0, 2),
        }

        payload = {
            "meta": self.meta,
            "chunks": [
                {
                    "text": c.text,
                    "source": c.source,
                    "chunk_id": c.chunk_id,
                    "heading": c.heading,
                }
                for c in self.chunks
            ],
            "embeddings": self.embeddings.tolist(),
        }
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        return self.meta

    def load(self) -> Dict[str, Any]:
        if not os.path.exists(self.cache_path):
            return self.build()

        with open(self.cache_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        meta = payload.get("meta", {})
        if meta.get("model_name") != self.model_name:
            return self.build()

        self.chunks = [Chunk(**c) for c in payload["chunks"]]
        self.embeddings = np.asarray(payload["embeddings"], dtype=np.float32)
        self.meta = meta
        return {"loaded": True, **meta}

    # -----------------------------
    # Retrieval
    # -----------------------------
    @staticmethod
    def _mmr(
        query_emb: np.ndarray,
        doc_embs: np.ndarray,
        top_k: int = 4,
        lambda_mult: float = 0.65,
        preselect: int = 16,
    ) -> List[int]:
        """
        Maximal Marginal Relevance:
        - pick docs that are relevant and diverse
        """
        # similarities to query
        sims = doc_embs @ query_emb
        # preselect most relevant
        cand = np.argsort(-sims)[:preselect].tolist()

        selected = []
        while cand and len(selected) < top_k:
            if not selected:
                best = cand[0]
                selected.append(best)
                cand.remove(best)
                continue

            best_score = -1e9
            best_idx = None
            for i in cand:
                rel = sims[i]
                # diversity penalty: max similarity to already selected
                div = max(doc_embs[i] @ doc_embs[j] for j in selected)
                score = lambda_mult * rel - (1 - lambda_mult) * div
                if score > best_score:
                    best_score = score
                    best_idx = i
            selected.append(best_idx)
            cand.remove(best_idx)

        return selected

    def retrieve(self, query: str, k: int = 6) -> List[Dict[str, Any]]:
        if self.embeddings is None or not self.chunks:
            self.load()

        q = query.strip()
        q_emb = self.embedder.encode([q], normalize_embeddings=True)
        q_emb = np.asarray(q_emb, dtype=np.float32)[0]

        idxs = self._mmr(q_emb, self.embeddings, top_k=k, lambda_mult=0.7, preselect=min(30, len(self.chunks)))

        # build results with dedupe by source+heading preference
        results = []
        seen = set()
        sims = (self.embeddings @ q_emb).astype(np.float32)

        for i in idxs:
            c = self.chunks[int(i)]
            key = (c.source, c.heading)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "score": float(sims[int(i)]),
                    "source": c.source,
                    "chunk_id": c.chunk_id,
                    "heading": c.heading,
                    "text": c.text,
                }
            )

        # sort by score descending (nice for UI/debug)
        results.sort(key=lambda x: x["score"], reverse=True)
        return results
