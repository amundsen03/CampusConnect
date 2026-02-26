from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import re
import json
import urllib.request
import urllib.error
from typing import List, Dict, Tuple

from .rag import RAGIndex

SERVER_VERSION = "campusconnect-rag-ollama-v5-2026-02-26"

APP_DIR = os.path.dirname(__file__)                 # .../Server/app
SERVER_DIR = os.path.dirname(APP_DIR)               # .../Server

KNOWLEDGE_DIR = os.path.join(APP_DIR, "knowledge")  # .../Server/app/knowledge
CACHE_DIR = os.path.join(SERVER_DIR, "cache")       # .../Server/cache
RAG_CACHE = os.path.join(CACHE_DIR, "rag_index.json")

DEVICE = "cpu"
GEN_BACKEND = os.environ.get("GEN_BACKEND", "ollama").lower()

# Ollama
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
# ✅ Faster default (override with env var OLLAMA_MODEL)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")

# RAG tuning via env
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "6"))
RAG_MAX_CHARS = int(os.environ.get("RAG_MAX_CHARS", "900"))
RAG_OVERLAP = int(os.environ.get("RAG_OVERLAP", "120"))

# Context trimming (keeps Ollama fast)
CTX_PER_CHUNK_CHARS = int(os.environ.get("CTX_PER_CHUNK_CHARS", "650"))
CTX_MAX_TOTAL_CHARS = int(os.environ.get("CTX_MAX_TOTAL_CHARS", "3500"))

# Ollama speed/safety
OLLAMA_TIMEOUT_S = int(os.environ.get("OLLAMA_TIMEOUT_S", "90"))
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "10m")

app = FastAPI(title="CampusConnect Local RAG Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # extension calls are fine in dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatReq(BaseModel):
    message: str
    temperature: float | None = 0.2
    max_new_tokens: int | None = 220
    debug: bool | None = False
    show_sources: bool | None = False  # ✅ default hidden

os.makedirs(CACHE_DIR, exist_ok=True)

rag = RAGIndex(
    knowledge_dir=KNOWLEDGE_DIR,
    cache_path=RAG_CACHE,
    max_chars=RAG_MAX_CHARS,
    overlap=RAG_OVERLAP,
)
rag.load()

# ----------------------------
# Language detection
# ----------------------------
def detect_language(user_text: str) -> str:
    t = (user_text or "").lower()
    if any(ch in t for ch in ["æ", "ø", "å"]):
        return "no"

    tokens = re.findall(r"[a-zA-ZæøåÆØÅ]+", t)
    no_hits = sum(w in tokens for w in ["hva", "hvordan", "hvor", "når", "kan", "må", "jeg", "vi", "dere", "innlandet", "kantina", "åpner", "stenger"])
    en_hits = sum(w in tokens for w in ["what", "how", "where", "when", "can", "must", "i", "we", "you", "university", "campus", "canteen", "open", "close"])
    return "en" if en_hits >= no_hits + 2 else "no"

def normalize_sources(retrieved: List[Dict]) -> List[str]:
    uniq = []
    for r in retrieved:
        s = r.get("source", "")
        if s and s not in uniq:
            uniq.append(s)
    return uniq

# ----------------------------
# Context builder
# ----------------------------
def build_context(retrieved: List[Dict]) -> str:
    blocks = []
    total = 0
    seen = set()

    for r in retrieved:
        src = r.get("source", "")
        heading = r.get("heading") or ""
        key = (src, heading)

        txt = (r.get("text") or "").strip()
        if not txt:
            continue
        if key in seen:
            continue
        seen.add(key)

        txt = txt[:CTX_PER_CHUNK_CHARS].strip()
        block = f"[SOURCE: {src}{(' / ' + heading) if heading else ''}]\n{txt}"

        if total + len(block) > CTX_MAX_TOTAL_CHARS:
            break

        blocks.append(block)
        total += len(block)

    return "\n\n---\n\n".join(blocks).strip()

# ----------------------------
# Prompting (no "Sources:" requirement)
# ----------------------------
def build_messages(user_message: str, retrieved: List[Dict]) -> Tuple[List[Dict], List[str], str]:
    sources = normalize_sources(retrieved)
    lang = detect_language(user_message)
    context = build_context(retrieved)

    if lang == "en":
        system = (
            "You are CampusConnect, a student assistant for Inland Norway University of Applied Sciences.\n"
            "Rules:\n"
            "- Use ONLY facts found in CONTEXT.\n"
            "- If the answer is not in CONTEXT, say: \"I can't find this in our knowledge base yet.\"\n"
            "- Be concise and direct.\n"
            "- Do NOT invent phone numbers, deadlines, prices, or rules.\n"
        )
        user = f"CONTEXT:\n{context}\n\nQuestion: {user_message}"
        out_lang = "en"
    else:
        system = (
            "Du er CampusConnect, en studentassistent for Universitetet i Innlandet.\n"
            "Regler:\n"
            "- Bruk KUN fakta som står i CONTEXT.\n"
            "- Hvis svaret ikke står i CONTEXT, skriv: \"Jeg finner ikke dette i kunnskapsbasen vår enda.\"\n"
            "- Svar kort og konkret.\n"
            "- Ikke finn på telefonnumre, frister, priser eller regler.\n"
        )
        user = f"CONTEXT:\n{context}\n\nSpørsmål: {user_message}"
        out_lang = "no"

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return messages, sources, out_lang

# ----------------------------
# Ollama generation
# ----------------------------
def ollama_chat(messages: List[Dict], temperature: float, max_new_tokens: int) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": temperature,
            "num_predict": max_new_tokens,
        },
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_S) as resp:
            out = json.loads(resp.read().decode("utf-8"))
            msg = out.get("message", {}) or {}
            return (msg.get("content") or "").strip()
    except urllib.error.URLError as e:
        return f"ERROR: Could not contact Ollama: {e}"
    except Exception as e:
        return f"ERROR: Ollama call failed: {e}"

# ----------------------------
# Postprocess + validity
# ----------------------------
def postprocess(reply: str) -> str:
    if not reply:
        return ""
    reply = reply.strip()
    reply = re.sub(r"^(assistant|Assistant)\s*:\s*", "", reply).strip()
    return reply

def looks_empty_or_useless(reply: str) -> bool:
    t = (reply or "").strip()
    if not t:
        return True
    low = t.lower().strip()
    if low.startswith("error:"):
        return True
    if len(t) < 6:
        return True
    return False

def ensure_sources_line(reply: str, sources: List[str], lang: str) -> str:
    # Only used in debug/show_sources mode
    if lang == "en":
        if "Sources:" not in reply:
            reply = reply.rstrip() + "\nSources: " + ", ".join(sources)
    else:
        if "Kilder:" not in reply:
            reply = reply.rstrip() + "\nKilder: " + ", ".join(sources)
    return reply

# ----------------------------
# Smart fallback: extract useful lines (times/prices/contact)
# ----------------------------
def extract_relevant_lines(user_message: str, retrieved: List[Dict], max_lines: int = 4) -> List[str]:
    q = (user_message or "").lower()
    joined = "\n".join((r.get("text") or "") for r in retrieved if r.get("text"))
    lines = [ln.strip() for ln in joined.splitlines() if ln.strip()]

    want_time = any(w in q for w in ["åpner", "åpning", "stenger", "open", "opening", "close", "hours", "tid"])
    want_price = any(w in q for w in ["pris", "koster", "kr", "nok", "price", "cost"])
    want_contact = any(w in q for w in ["kontakt", "epost", "email", "telefon", "phone"])

    scored = []
    for ln in lines:
        s = 0
        if want_time and re.search(r"\b\d{1,2}[:.]\d{2}\b", ln): s += 3
        if want_time and any(day in ln.lower() for day in ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "monday", "tuesday", "wednesday", "thursday", "friday", "man", "tor", "fre"]): s += 2
        if want_price and re.search(r"\b(kr|nok)\b|\d+[,\.]?\d*\s*(kr|nok)", ln.lower()): s += 3
        if want_contact and ("@" in ln or re.search(r"\b\d{2}\s?\d{2}\s?\d{2}\s?\d{2}\b", ln)): s += 3

        for kw in ["kantine", "canteen", "parkering", "parking", "brann", "fire", "studentprest", "chaplain"]:
            if kw in q and kw in ln.lower():
                s += 2

        if s > 0:
            scored.append((s, ln))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [ln for _, ln in scored[:max_lines]]

def fallback_answer(user_message: str, retrieved: List[Dict]) -> str:
    lang = detect_language(user_message)

    if not retrieved:
        return "I can't find this in our knowledge base yet." if lang == "en" else "Jeg finner ikke dette i kunnskapsbasen vår enda."

    best_lines = extract_relevant_lines(user_message, retrieved)
    if best_lines:
        return " ".join(best_lines[:2]).strip()

    return "I can't find this in our knowledge base yet." if lang == "en" else "Jeg finner ikke dette i kunnskapsbasen vår enda."

# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
def health():
    md_files = 0
    if os.path.isdir(KNOWLEDGE_DIR):
        md_files = len([f for f in os.listdir(KNOWLEDGE_DIR) if f.lower().endswith(".md")])

    return {
        "ok": True,
        "server_version": SERVER_VERSION,
        "device": DEVICE,
        "gen_backend": GEN_BACKEND,
        "model": OLLAMA_MODEL if GEN_BACKEND == "ollama" else "n/a",
        "ollama_url": OLLAMA_URL if GEN_BACKEND == "ollama" else None,
        "knowledge_files": md_files,
        "rag": {**rag.meta, "top_k": RAG_TOP_K, "max_chars": RAG_MAX_CHARS, "overlap": RAG_OVERLAP},
        "paths": {
            "server_dir": SERVER_DIR,
            "app_dir": APP_DIR,
            "knowledge_dir": KNOWLEDGE_DIR,
            "rag_cache": RAG_CACHE,
        },
    }

@app.post("/reindex")
def reindex():
    info = rag.build()
    return {"ok": True, **info}

@app.post("/chat")
def chat(req: ChatReq):
    msg = (req.message or "").strip()
    if not msg:
        return {"reply": "Skriv inn et spørsmål.", "sources": []}

    temperature = float(req.temperature or 0.2)
    temperature = max(0.0, min(1.5, temperature))

    max_new = int(req.max_new_tokens or 220)
    max_new = max(48, min(320, max_new))

    retrieved = rag.retrieve(msg, k=RAG_TOP_K)
    out_lang = detect_language(msg)

    should_show_sources = bool(req.debug or req.show_sources)
    sources = normalize_sources(retrieved)

    # If no context -> fallback
    if not retrieved:
        reply = fallback_answer(msg, retrieved)
        if should_show_sources:
            reply = ensure_sources_line(reply, sources, lang=("en" if out_lang == "en" else "no"))
        return {"reply": reply, "sources": retrieved if should_show_sources else []}

    # Normal LLM path
    messages, _, lang = build_messages(msg, retrieved)

    reply = ""
    if GEN_BACKEND == "ollama":
        reply = postprocess(ollama_chat(messages, temperature=temperature, max_new_tokens=max_new))

        # If Ollama failed/timeout, do NOT show ERROR to user. Use fallback.
        if looks_empty_or_useless(reply):
            reply = fallback_answer(msg, retrieved)
    else:
        reply = fallback_answer(msg, retrieved)

    if should_show_sources:
        reply = ensure_sources_line(reply, sources, lang=("en" if out_lang == "en" else "no"))
        return {"reply": reply, "sources": retrieved}

    return {"reply": reply, "sources": []}