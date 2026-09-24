import streamlit as st
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import re
import uuid
import json
from datetime import datetime
from pathlib import Path

from QueryDesk.config import settings
from QueryDesk.core.conversation.session import SessionManager
from QueryDesk.core.evaluation.ragas_eval import RAGASEvaluator
from QueryDesk.core.feedback.manager import FeedbackManager
from QueryDesk.core.generation.generator import RAGGenerator
from QueryDesk.core.ingestion.pipeline import IngestionPipeline
from QueryDesk.core.retrieval.bm25_store import BM25Store
from QueryDesk.core.retrieval.hybrid import HybridRetriever
from QueryDesk.core.retrieval.pinecone_store import PineconeStore
from QueryDesk.core.ingestion.gemini_embedder import GeminiEmbedder
from QueryDesk.models.schemas import ChatMessage, MessageRole, SourceReference
from QueryDesk.utils.logger import logger

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="QueryDesk",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,200..700;1,9..40,200..700&family=DM+Mono:wght@300;400;500&display=swap');

:root {
    --bg:          #F1EDE6;   /* soft warm cream — less clinical than pure white */
    --s1:          #EAE4D9;   /* sidebar — warm tint, subtle separation from bg */
    --s2:          #F8F5F0;   /* card surface — soft off-white, not stark white */
    --s3:          #E5DDD0;   /* hover state — warm wash */
    --b0:          rgba(22,51,58,0.06);
    --b1:          rgba(22,51,58,0.13);
    --t1:          #16333A;   /* primary text — dark teal, from your darkest swatch */
    --t2:          #55625F;   /* secondary text — warmed slightly to match new bg */
    --t3:          #8C8F84;   /* tertiary text / placeholders — warmed */
    --accent:      #3E7472;   /* primary accent — deepened for contrast on light bg */
    --accent-soft: #88BDBC;   /* your original lighter teal — soft fills only, not text/buttons */
    --accent-dark: #2A5654;   /* hover state */
    --ac-lo:       rgba(62,116,114,0.10);
    --ac-glow:     rgba(62,116,114,0.20);
    --green:       #059669;   /* deepened from standard green for contrast on light bg */
    --green-lo:    rgba(5,150,105,0.09);
    --red:         #dc2626;   /* deepened from standard red for contrast on light bg */
    --amber:       #d97706;   /* deepened from standard amber for contrast on light bg */
    --amber-lo:    rgba(217,119,6,0.09);
    --cyan:        #3E7472;   /* reuses accent — decorative info tags */
    --cyan-lo:     rgba(62,116,114,0.08);
    --warm:        #6E6658;   /* your taupe — reserved, currently unused */
    --r-sm:        8px;
    --r-md:        14px;
}

*, *::before, *::after { box-sizing: border-box; }

html, body {
    font-family: 'DM Sans', sans-serif;
    -webkit-font-smoothing: antialiased;
}

.stApp {
    background: var(--bg);
    color: var(--t1);
    font-family: 'DM Sans', sans-serif;
}

/* ── Header Cleanup ── */
div[data-testid="stDecoration"] { display: none !important; }
#MainMenu, footer, .stDeployButton { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; }
header[data-testid="stHeader"] button { color: var(--t1) !important; }

/* ── Main content ── */
.block-container {
    padding: 2rem 2.5rem 8rem !important;
    max-width: 860px !important;
    margin: 0 auto !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--s3); border-radius: 99px; }

/* ════════════════════════════════════════
   SIDEBAR
════════════════════════════════════════ */
section[data-testid="stSidebar"] {
    background: var(--s1) !important;
    border-right: 1px solid var(--b0) !important;
}
[data-testid="stSidebarContent"] { padding: 0 14px 24px !important; }
[data-testid="stSidebarNav"] { display: none !important; }

.sb-lbl {
    font-size: 0.6rem; font-weight: 700; color: var(--t3);
    text-transform: uppercase; letter-spacing: 0.16em;
    padding: 12px 2px 6px; margin-top: 4px;
}

/* Sidebar buttons */
section[data-testid="stSidebar"] .stButton > button {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.82rem !important; font-weight: 600 !important;
    color: var(--t1) !important; background: var(--ac-lo) !important;
    border: 1px solid rgba(136,189,188,0.22) !important;
    border-radius: var(--r-sm) !important;
    padding: 9px 14px !important; width: 100% !important;
    transition: all 0.14s !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: var(--accent) !important; border-color: var(--accent) !important; color: white !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: var(--accent) !important; border-color: var(--accent) !important; color: white !important;
    font-weight: 700 !important;
}

.model-badge {
    display: flex; align-items: center; gap: 8px; padding: 10px 12px;
    background: var(--s2); border: 1px solid var(--b1);
    border-radius: var(--r-sm); margin-bottom: 10px;
}
.model-icon { font-size: 0.85rem; flex-shrink: 0; }
.model-name { font-size: 0.75rem; font-weight: 600; color: var(--t1); }
.model-sub { font-size: 0.65rem; color: var(--t3); margin-top: 1px; }

.sb-status { padding-top: 14px; border-top: 1px solid var(--b0); margin-top: 14px; }
.status-pill {
    display: inline-flex; align-items: center; gap: 7px;
    background: var(--green-lo); border: 1px solid rgba(5,150,105,0.16);
    border-radius: 99px; padding: 5px 11px;
    font-size: 0.68rem; font-weight: 600; color: var(--green);
}
.sdot {
    width: 5px; height: 5px; background: var(--green);
    border-radius: 50%; box-shadow: 0 0 6px var(--green);
    animation: blink 2.2s ease-in-out infinite; flex-shrink: 0;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.3} }

/* ════════════════════════════════════════
   CHAT INPUT
════════════════════════════════════════ */
[data-testid*="ChatInput"],
[data-testid*="Bottom"] {
    background: var(--bg) !important;
    border-top: 1px solid var(--b0) !important;
}
.stChatInput,
.stChatInput > div,
.stChatInput [data-baseweb="base-input"],
.stChatInput [data-baseweb="textarea"] {
    background: var(--s2) !important; border: 1px solid var(--b1) !important;
    border-radius: var(--r-md) !important; box-shadow: none !important;
    transition: border-color 0.18s, box-shadow 0.18s !important;
}
.stChatInput:focus-within,
.stChatInput [data-baseweb="base-input"]:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--ac-glow) !important;
}
[data-testid*="ChatInput"] textarea {
    color: var(--t1) !important; font-family: 'DM Sans', sans-serif !important;
    font-size: 0.93rem !important; background: transparent !important;
    outline: none !important; box-shadow: none !important;
    border: none !important; caret-color: var(--accent) !important;
}
[data-testid*="ChatInput"] textarea:focus { outline: none !important; box-shadow: none !important; }
[data-testid*="ChatInput"] textarea::placeholder { color: var(--t3) !important; }
.stChatInput button { background: var(--accent) !important; border-radius: 8px !important; }

/* ════════════════════════════════════════
   MAIN AREA BUTTONS (default)
════════════════════════════════════════ */
.stButton > button:not(#___spec),
.stDownloadButton > button:not(#___spec) {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.75rem !important; font-weight: 600 !important;
    color: var(--t2) !important; background: var(--s2) !important;
    border: 1px solid var(--b1) !important; border-radius: 6px !important;
    padding: 5px 12px !important; transition: all 0.14s !important;
    min-height: 32px !important; line-height: 1 !important;
    display: flex !important; align-items: center !important; justify-content: center !important;
}
.stButton > button:not(#___spec):hover,
.stDownloadButton > button:not(#___spec):hover {
    color: var(--t1) !important; background: var(--s3) !important;
    border-color: var(--b1) !important;
}
.stButton > button:not(#___spec):disabled {
    opacity: 0.35 !important; cursor: not-allowed !important;
}

/* Accent (primary) buttons */
.stButton > button:not(#___spec)[kind="primary"] {
    color: white !important; background: var(--accent) !important;
    border-color: var(--accent) !important; font-weight: 600 !important;
}
.stButton > button:not(#___spec)[kind="primary"]:hover {
    background: var(--accent-dark) !important; border-color: var(--accent-dark) !important; color: white !important;
}

/* ════════════════════════════════════════
   MISC WIDGETS
════════════════════════════════════════ */
.stProgress > div { background: var(--s3) !important; border-radius: 99px !important; }
.stProgress > div > div { background: var(--accent) !important; border-radius: 99px !important; }
.stProgress + div, [data-testid="stText"] { color: var(--t2) !important; }

[data-testid*="FileUploadDropzone"]:not(#___spec),
[data-testid*="FileUploader"]:not(#___spec) {
    background: var(--s2) !important;
    border: 1.5px dashed var(--b1) !important;
    border-radius: var(--r-md) !important;
    padding: 24px !important;
}
[data-testid*="FileUploadDropzone"]:not(#___spec) *,
[data-testid*="FileUploader"]:not(#___spec) * { color: var(--t2) !important; }
[data-testid*="FileUploadDropzone"]:not(#___spec) button,
[data-testid*="FileUploader"]:not(#___spec) button {
    background: var(--s3) !important; color: var(--t1) !important;
    border: 1px solid var(--b1) !important; border-radius: 6px !important;
    font-size: 0.78rem !important;
}
[data-testid="stFileUploader"] label { color: var(--t2) !important; font-size: 0.82rem !important; }
[data-testid="stFileUploadDeleteBtn"] { color: var(--t2) !important; }

/* Chat messages — strip Streamlit's own chrome */
[data-testid="stChatMessage"] { background: transparent !important; padding: 0 !important; border: none !important; }
[data-testid="stChatMessage"] p:not(#___spec) { color: var(--t1) !important; }
hr { border-color: var(--b0) !important; margin: 24px 0 !important; }

.stAlert {
    background: var(--s2) !important;
    border-radius: var(--r-sm) !important;
    border: 1px solid var(--b1) !important;
}
[data-testid="stAlert"] p { color: var(--t1) !important; }
div[data-baseweb="notification"] { background: var(--s2) !important; color: var(--t1) !important; }

.stSpinner > div { color: var(--t2) !important; }
.stSpinner > div > div { border-top-color: var(--accent) !important; }

/* ════════════════════════════════════════
   ASK PAGE — HERO
════════════════════════════════════════ */
.hero { text-align: center; padding: 68px 24px 36px; }
.hero-badge {
    display: inline-flex; align-items: center; gap: 7px;
    background: var(--ac-lo); border: 1px solid rgba(136,189,188,0.18);
    border-radius: 99px; padding: 5px 14px;
    font-size: 0.67rem; font-weight: 700; color: var(--accent);
    letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 28px;
}
.hero-h1 {
    font-size: clamp(2.4rem, 5.5vw, 3.8rem);
    font-weight: 700; letter-spacing: -0.055em; line-height: 1.02;
    color: var(--t1); margin-bottom: 18px;
}
.hero-h1 em {
    font-style: normal;
    color: var(--accent);
}
.hero-sub {
    font-size: 0.975rem; color: var(--t2);
    max-width: 380px; line-height: 1.65; margin: 0 auto 44px;
}

/* ════════════════════════════════════════
   ASK PAGE — CONVERSATION
════════════════════════════════════════ */

/* Sources label */
.src-lbl {
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.13em; color: var(--t3); margin-bottom: 10px;
}

/* Source card */
.src-card {
    background: var(--s2); border: 1px solid var(--b0);
    border-radius: var(--r-sm); padding: 12px 14px;
    min-height: 76px;
    transition: border-color 0.14s;
}
.src-card:hover { border-color: var(--b1); }
.src-fname {
    font-size: 0.77rem; font-weight: 600; color: var(--t1);
    margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.src-meta {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    margin-bottom: 7px;
}
.src-rank, .src-score, .src-page {
    display: inline-flex; align-items: center;
    font-size: 0.62rem; font-weight: 700;
    border-radius: 999px; padding: 3px 7px;
}
.src-rank { color: var(--accent); background: var(--ac-lo); }
.src-score { color: var(--green); background: var(--green-lo); }
.src-page { color: var(--cyan); background: var(--cyan-lo); }
.src-snip {
    font-size: 0.7rem; color: var(--t2); line-height: 1.55;
    overflow: hidden; display: -webkit-box;
    -webkit-line-clamp: 3; -webkit-box-orient: vertical;
}

/* ── Action bar (feedback + copy) ── */
.action-bar { display: flex; align-items: center; gap: 6px; margin-top: 12px; flex-wrap: wrap; }

/* Vertically align feedback button columns */
div[data-testid="stHorizontalBlock"] {
    align-items: center !important;
    gap: 6px !important;
}
div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
    display: flex !important;
    align-items: center !important;
    min-width: 0 !important;
}

/* Suggestion chips */
.sugg-row { margin-top: 14px; }

/* ════════════════════════════════════════
   SOURCES PAGE
════════════════════════════════════════ */
.page-head { margin-bottom: 24px; }
.page-title {
    font-size: 1.65rem; font-weight: 700;
    letter-spacing: -0.04em; color: var(--t1); margin-bottom: 4px;
}
.page-sub { font-size: 0.875rem; color: var(--t2); }

.doc-row {
    display: flex; align-items: center; gap: 12px;
    background: var(--s2); border: 1px solid var(--b0);
    border-radius: var(--r-sm); padding: 13px 16px;
    margin-bottom: 7px; transition: border-color 0.14s;
}
.doc-row:hover { border-color: var(--b1); }
.doc-icon { font-size: 0.9rem; flex-shrink: 0; }
.doc-name {
    font-size: 0.875rem; font-weight: 500; color: var(--t1);
    flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.doc-ext {
    font-size: 0.65rem; font-family: 'DM Mono', monospace;
    color: var(--t3); background: var(--s3); padding: 2px 7px; border-radius: 4px;
}

.empty-state { text-align: center; padding: 56px 0; color: var(--t3); }
.empty-icon { font-size: 1.8rem; margin-bottom: 12px; }
.empty-msg { font-size: 0.875rem; }

/* ════════════════════════════════════════
   EXPLORER PAGE
════════════════════════════════════════ */
.chunk-card {
    background: var(--s2); border: 1px solid var(--b0);
    border-radius: var(--r-md); padding: 16px 20px;
    margin-bottom: 10px; transition: border-color 0.15s;
}
.chunk-card:hover { border-color: var(--b1); }
.chunk-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.chunk-doc {
    font-size: 0.72rem; font-weight: 600; color: var(--accent);
    background: var(--ac-lo); padding: 3px 10px; border-radius: 4px;
}
.chunk-page { font-size: 0.65rem; font-weight: 500; color: var(--t3); font-family: 'DM Mono', monospace; }
.chunk-id { font-size: 0.6rem; color: var(--t3); font-family: 'DM Mono', monospace; margin-left: auto; }
.chunk-text { font-size: 0.835rem; color: var(--t2); line-height: 1.7; white-space: pre-wrap; }
.search-stats { font-size: 0.72rem; color: var(--t3); font-weight: 600; margin-bottom: 16px; letter-spacing: 0.03em; }

/* Search input */
div[data-testid="stTextInput"] input {
    background: var(--s2) !important; border: 1px solid var(--b1) !important;
    border-radius: var(--r-sm) !important; color: var(--t1) !important;
    font-family: 'DM Sans', sans-serif !important;
    padding: 10px 14px !important;
}
div[data-testid="stTextInput"] input:focus {
    border-color: var(--accent) !important; box-shadow: 0 0 0 3px var(--ac-glow) !important;
}
div[data-testid="stTextInput"] input::placeholder { color: var(--t3) !important; }
div[data-testid="stTextInput"] label { color: var(--t2) !important; }

/* Select box */
div[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    background: var(--s2) !important; border: 1px solid var(--b1) !important;
    border-radius: var(--r-sm) !important; color: var(--t1) !important;
}
div[data-testid="stSelectbox"] [data-baseweb="select"] * { color: var(--t1) !important; }
[data-baseweb="popover"] { background: var(--s2) !important; border: 1px solid var(--b1) !important; }
[data-baseweb="menu"] { background: var(--s2) !important; }
[data-baseweb="menu"] li { color: var(--t2) !important; font-size: 0.84rem !important; }
[data-baseweb="menu"] li:hover { background: var(--s3) !important; color: var(--t1) !important; }
[data-baseweb="menu"] li[aria-selected="true"] { background: var(--ac-lo) !important; color: var(--accent) !important; }

/* ════════════════════════════════════════
   ANALYTICS PAGE
════════════════════════════════════════ */
.kpi-card {
    background: var(--s2); border: 1px solid var(--b0);
    border-radius: var(--r-md); padding: 20px 22px;
    position: relative; overflow: hidden;
}
.kpi-card::after {
    content: ''; position: absolute;
    top: 0; left: 0; right: 0; height: 1.5px;
    background: linear-gradient(90deg, var(--accent) 0%, transparent 70%);
}
.kpi-card.green::after { background: linear-gradient(90deg, var(--green) 0%, transparent 70%); }
.kpi-card.amber::after { background: linear-gradient(90deg, var(--amber) 0%, transparent 70%); }
.kpi-card.cyan::after  { background: linear-gradient(90deg, var(--cyan)  0%, transparent 70%); }
.kpi-lbl {
    font-size: 0.65rem; font-weight: 700; color: var(--t3);
    text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 10px;
}
.kpi-val {
    font-family: 'DM Mono', monospace; font-size: 2.1rem;
    font-weight: 400; color: var(--t1); letter-spacing: -0.03em;
}
.panel {
    background: var(--s2); border: 1px solid var(--b0);
    border-radius: var(--r-md); padding: 20px 22px;
}
.panel-title {
    font-size: 0.67rem; font-weight: 700; color: var(--t3);
    text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 16px;
}
.log-card {
    background: var(--s3); border-radius: var(--r-sm);
    padding: 11px 14px; margin-bottom: 7px;
}
.log-date { font-size: 0.65rem; color: var(--t3); font-family: 'DM Mono', monospace; margin-bottom: 3px; }
.log-q { font-size: 0.855rem; color: var(--t1); font-weight: 500; }
.gap-card {
    background: rgba(220,38,38,0.05); border: 1px solid rgba(220,38,38,0.14);
    border-radius: var(--r-sm); padding: 11px 14px; margin-bottom: 7px;
}
.gap-lbl {
    font-size: 0.62rem; font-weight: 700; color: var(--red);
    text-transform: uppercase; letter-spacing: 0.09em; margin-bottom: 3px;
}
.gap-q { font-size: 0.855rem; color: var(--t1); font-weight: 500; }
.ok-state { text-align: center; padding: 28px 0; }
.ok-icon { font-size: 1.4rem; margin-bottom: 8px; }
.ok-msg { font-size: 0.83rem; color: var(--green); font-weight: 600; }

.fb-stat { display: flex; align-items: center; gap: 10px; padding: 10px 0; }
.fb-bar-bg { flex: 1; height: 6px; background: var(--s3); border-radius: 99px; overflow: hidden; }
.fb-bar-fill { height: 100%; border-radius: 99px; transition: width 0.5s ease; }
.fb-bar-fill.pos { background: var(--green); }
.fb-bar-fill.neg { background: var(--red); }
.fb-pct { font-size: 0.75rem; font-family: 'DM Mono', monospace; color: var(--t2); min-width: 40px; text-align: right; }
.fb-label { font-size: 0.78rem; font-weight: 500; color: var(--t2); min-width: 70px; }

.chart-title {
    font-size: 0.67rem; font-weight: 700; color: var(--t3);
    text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 12px;
}
[data-testid="stVegaLiteChart"] { background: transparent !important; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px; background: var(--s1);
    border-radius: var(--r-sm); padding: 3px;
    border-bottom: none !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important; color: var(--t2) !important;
    border-radius: 6px !important; font-size: 0.82rem !important;
    font-weight: 500 !important; padding: 8px 16px !important;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--t1) !important; background: var(--s2) !important; }
.stTabs [aria-selected="true"] { background: var(--s3) !important; color: var(--t1) !important; font-weight: 600 !important; }
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }
.stTabs [data-baseweb="tab-border"] { display: none !important; }

button[data-testid="stBaseButton-secondary"]:disabled { opacity: 0.4 !important; }
</style>
""", unsafe_allow_html=True)


# ── Services ──────────────────────────────────────────────────────────────────
@st.cache_resource
def get_services():
    pinecone_store = PineconeStore()
    bm25_store     = BM25Store()
    retriever      = HybridRetriever(pinecone_store, bm25_store)
    return (
        retriever,
        RAGGenerator(retriever),
        IngestionPipeline(pinecone_store, bm25_store),
        SessionManager(),
        RAGASEvaluator(),
        FeedbackManager(),
        bm25_store,
    )

# ── Session state ─────────────────────────────────────────────────────────────
if "messages"       not in st.session_state: st.session_state.messages       = []
if "session_id"     not in st.session_state: st.session_state.session_id     = str(uuid.uuid4())
if "uploader_key"   not in st.session_state: st.session_state.uploader_key   = 0
if "nav"            not in st.session_state: st.session_state.nav            = "Ask"
if "feedback_given" not in st.session_state: st.session_state.feedback_given = {}

# Handle nav redirect from switch_conversation / clear_all
if "_nav_redirect" in st.session_state:
    st.session_state.nav = st.session_state.pop("_nav_redirect")

retriever, generator, pipeline, session_manager, evaluator, feedback_mgr, bm25_store = get_services()

# ── Auto-ingest data/docs on startup ─────────────────────────────────────────
DOCS_DIR = Path("data/docs")
DOCS_DIR.mkdir(parents=True, exist_ok=True)

def auto_ingest_docs():
    # Check Pinecone for existing documents to avoid re-ingesting on Streamlit Cloud
    from QueryDesk.core.retrieval.pinecone_store import PineconeStore
    pinecone_store = PineconeStore()
    
    # Get all unique doc names from Pinecone metadata
    pinecone_doc_names = set()
    try:
        # Query Pinecone to get all vectors and extract doc names from metadata
        # Using a simple query to fetch metadata
        query_response = pinecone_store._index.query(
            vector=[0] * settings.embedding_dim,  # dummy vector
            top_k=10000,  # fetch all
            include_metadata=True,
            filter={}  # no filter to get all
        )
        for match in query_response.get("matches", []):
            metadata = match.get("metadata", {})
            doc_name = metadata.get("doc_name")
            if doc_name:
                pinecone_doc_names.add(doc_name)
        logger.info(f"Found {len(pinecone_doc_names)} documents in Pinecone")
    except Exception as e:
        logger.warning(f"Failed to query Pinecone for existing docs: {e}")
        # Fallback to local registry if Pinecone query fails
        pinecone_doc_names = {d.name for d in pipeline.get_all_documents()}
    
    for md_file in sorted(DOCS_DIR.glob("*.md")):
        if md_file.name not in pinecone_doc_names:
            logger.info(f"Auto-ingesting: {md_file.name}")
            pipeline.ingest(str(md_file), md_file.name)
        else:
            logger.info(f"Skipping {md_file.name} (already in Pinecone)")

@st.cache_resource
def run_auto_ingest():
    auto_ingest_docs()
    return True

with st.spinner("Setting up knowledge base — this can take a minute on first launch…"):
    run_auto_ingest()

def sync_session_to_state(session):
    st.session_state.messages = []
    st.session_state.feedback_given = {}

    for msg in session.messages:
        message = {
            "role": msg.role.value,
            "content": msg.content,
        }
        if msg.role == MessageRole.ASSISTANT:
            message["msg_id"] = msg.message_id
            message["sources"] = [
                {
                    "name": source.doc_name,
                    "page": source.page_number,
                    "score": source.relevance_score,
                    "score_label": "Top match" if idx == 1 else f"Source {idx}",
                    "rank": idx,
                }
                for idx, source in enumerate(msg.sources, start=1)
            ]
            message["suggestions"] = msg.suggestions
            feedback = feedback_mgr.get_feedback_for_message(msg.message_id)
            if feedback:
                st.session_state.feedback_given[msg.message_id] = feedback
        st.session_state.messages.append(message)


def append_user_message(content: str) -> None:
    st.session_state.messages.append({"role": "user", "content": content})
    session_manager.add_message(
        st.session_state.session_id,
        ChatMessage(role=MessageRole.USER, content=content),
    )


def persist_assistant_message(content: str, msg_id: str, sources: list[dict], suggestions: list[str]) -> None:
    session_manager.add_message(
        st.session_state.session_id,
        ChatMessage(
            message_id=msg_id,
            role=MessageRole.ASSISTANT,
            content=content,
            sources=[
                SourceReference(
                    doc_name=source["name"],
                    chunk_content=source.get("content", ""),
                    page_number=source.get("page"),
                    relevance_score=source.get("score", 0.0),
                )
                for source in sources
            ],
            suggestions=suggestions,
        ),
    )


def reset_chat():
    st.session_state.messages        = []
    st.session_state.session_id      = str(uuid.uuid4())
    st.session_state.feedback_given  = {}


def switch_conversation(sid):
    session = session_manager.get_session(sid)
    if session:
        sync_session_to_state(session)
        st.session_state.session_id = sid
        st.session_state._nav_redirect = "Ask"


def clear_all_conversations():
    import shutil
    from pathlib import Path as _Path
    sessions_dir = _Path("data/sessions")
    if sessions_dir.exists():
        shutil.rmtree(sessions_dir)
        sessions_dir.mkdir(parents=True, exist_ok=True)
    session_manager._sessions        = {}
    st.session_state.messages        = []
    st.session_state.session_id      = str(uuid.uuid4())
    st.session_state.feedback_given  = {}
    st.session_state._nav_redirect   = "Ask"


# ── Helper: render source cards ───────────────────────────────────────────────
def render_sources(sources):
    if not sources:
        return
    cards_html = "<div class='src-lbl'>SOURCES</div><div style='display:flex;gap:12px;margin-bottom:6px;'>"
    for i, s in enumerate(sources[:3]):
        page_info = f"<span class='src-page'>Page {s['page']}</span>" if s.get("page") else ""
        name = str(s.get('name', ''))
        score_label = str(s.get('score_label', 'Match'))
        rank = int(s.get('rank', i + 1))
        cards_html += (
            f"<div class='src-card' style='flex:1;min-width:0;'>"
            f"<div class='src-fname'>📄 {name}</div>"
            f"<div class='src-meta'>"
            f"<div class='src-rank'>#{rank}</div>"
            f"<div class='src-score'>{score_label}</div>"
            f"{page_info}"
            f"</div></div>"
        )
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)


# ════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════
with st.sidebar:
    st.markdown("<div class='sb-lbl'>Navigation</div>", unsafe_allow_html=True)
    nav_options = [
        ("Ask",       "◇  Ask"),
        ("Sources",   "⊞  Sources"),
        ("Explorer",  "⬡  Explorer"),
        ("Analytics", "◎  Analytics"),
        ("Recents",   "◷  Recents"),
    ]
    for nav_key, nav_label in nav_options:
        is_active = st.session_state.nav == nav_key
        if st.button(
            nav_label,
            key=f"navbtn_{nav_key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state.nav = nav_key
            st.rerun()
    nav = st.session_state.nav

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.button("＋  New conversation", on_click=reset_chat, use_container_width=True)

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='sb-lbl'>Model</div>", unsafe_allow_html=True)
    st.markdown("""
        <div class="model-badge">
            <div class="model-icon">✦</div>
            <div class="model-info">
                <div class="model-name">Gemini</div>
                <div class="model-sub">LlamaIndex Fusion · Pinecone + BM25 · RAGAS</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("""
        <div class="sb-status">
            <div class="status-pill">
                <div class="sdot"></div>
                RAG Engine · Online
            </div>
        </div>
    """, unsafe_allow_html=True)


# ════════════════════════════════════════
# ASK PAGE
# ════════════════════════════════════════
if nav == "Ask":

    # ── Hero (empty state) ────────────────────────────────────────────────────
    if not st.session_state.messages:
        st.markdown("""
            <div class="hero">
                <div class="hero-badge">◈ &nbsp;Powered by Gemini · RAG</div>
                <div class="hero-h1"><em>QueryDesk</em></div>
                <div class="hero-sub">Smart HelpDesk Assistant</div>
            </div>
        """, unsafe_allow_html=True)

        prompts = [
            ("Annual Leave Policy", "How many days of annual leave am I entitled to?"),
            ("Performance Reviews", "What is the performance rating scale and how are reviews conducted?"),
            ("401(k) Benefits",    "What is the company 401(k) match and vesting schedule?"),
        ]
        c1, c2, c3 = st.columns(3)
        for col, (label, query) in zip([c1, c2, c3], prompts):
            with col:
                if st.button(label, use_container_width=True):
                    append_user_message(query)
                    st.rerun()

    # ── Conversation thread ───────────────────────────────────────────────────
    else:
        # Export button
        exp_col, _ = st.columns([1.5, 4.5])
        with exp_col:
            md_lines = [f"# QueryDesk Conversation\n_Exported {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n---\n"]
            for msg in st.session_state.messages:
                if msg["role"] == "user":
                    md_lines.append(f"## 🙋 {msg['content']}\n")
                else:
                    md_lines.append(f"### 🤖 QueryDesk\n{msg['content']}\n")
                    for s in msg.get("sources", []):
                        md_lines.append(f"- 📄 {s['name']}")
                    md_lines.append("---\n")
            st.download_button(
                "📥  Export Chat",
                data="\n".join(md_lines),
                file_name=f"QueryDesk_chat_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
            )

        # Render each stored message
        for idx, msg in enumerate(st.session_state.messages):

            if msg["role"] == "user":
                with st.chat_message("user"):
                    st.markdown(msg["content"])

            else:
                with st.chat_message("assistant"):
                    # Sources inside the bubble
                    render_sources(msg.get("sources", []))

                    # Answer
                    st.markdown(msg["content"])

                    # Feedback + copy row
                    msg_id      = msg.get("msg_id", f"msg_{idx}")
                    existing_fb = st.session_state.feedback_given.get(msg_id)

                    fb1, fb2, fb3, _ = st.columns([0.45, 0.45, 0.75, 4.35])
                    with fb1:
                        if existing_fb == "positive":
                            st.button("✓ Helpful", key=f"fb_pos_{msg_id}", disabled=True, use_container_width=True)
                        elif existing_fb == "negative":
                            st.button("👍", key=f"fb_pos_{msg_id}", disabled=True, use_container_width=True)
                        else:
                            if st.button("👍", key=f"fb_pos_{msg_id}", use_container_width=True):
                                feedback_mgr.add_feedback(msg_id, st.session_state.session_id, "positive")
                                st.session_state.feedback_given[msg_id] = "positive"
                                st.rerun()
                    with fb2:
                        if existing_fb == "negative":
                            st.button("✗ Flagged", key=f"fb_neg_{msg_id}", disabled=True, use_container_width=True)
                        elif existing_fb == "positive":
                            st.button("👎", key=f"fb_neg_{msg_id}", disabled=True, use_container_width=True)
                        else:
                            if st.button("👎", key=f"fb_neg_{msg_id}", use_container_width=True):
                                feedback_mgr.add_feedback(msg_id, st.session_state.session_id, "negative")
                                st.session_state.feedback_given[msg_id] = "negative"
                                st.rerun()
                    with fb3:
                        st.download_button(
                            "📋 Copy",
                            data=msg["content"],
                            file_name="QueryDesk_answer.txt",
                            mime="text/plain",
                            key=f"copy_{msg_id}",
                            use_container_width=True,
                        )

                    # Suggestion chips
                    suggestions = msg.get("suggestions", [])
                    if suggestions:
                        sugg_cols = st.columns(min(len(suggestions), 3))
                        for ci, sug in enumerate(suggestions[:3]):
                            with sugg_cols[ci]:
                                if st.button(f"→ {sug}", key=f"sugg_{idx}_{ci}", use_container_width=True):
                                    append_user_message(sug)
                                    st.rerun()

    # ── Chat input ────────────────────────────────────────────────────────────
    user_input = st.chat_input("Ask a question about your documentation…")
    if user_input:
        append_user_message(user_input)
        st.rerun()

    # Trigger response if last message is from user
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        query = st.session_state.messages[-1]["content"]

        try:
            with st.spinner("Searching knowledge base…"):
                res     = retriever.retrieve(query)
                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages
                ]
                resolved_sources = generator.resolve_sources(query, res.chunks, history)
                max_source_score = max(
                    (s.relevance_score for s in resolved_sources),
                    default=1.0,
                )
                sources = [
                    {
                        "name": s.doc_name,
                        "page": s.page_number,
                        "score": s.relevance_score,
                        "score_label": (
                            "Top match"
                            if idx == 1
                            else f"{int(round((s.relevance_score / max_source_score) * 100))}% relevance"
                        ),
                        "rank": idx,
                    }
                    for idx, s in enumerate(resolved_sources, start=1)
                ]

            with st.chat_message("assistant"):
                render_sources(sources)
                full_answer = st.write_stream(
                    generator.generate_stream(query, res.chunks, history)
                )

            suggestions = generator._generate_suggestions(query, res.chunks)
            msg_id = str(uuid.uuid4())
            evaluator.evaluate(
                query, full_answer, res.chunks,
                st.session_state.session_id, msg_id,
            )

            assistant_msg = {
                "role":        "assistant",
                "content":     full_answer,
                "msg_id":      msg_id,
                "sources":     sources,
                "suggestions": suggestions,
            }
            st.session_state.messages.append(assistant_msg)
            persist_assistant_message(full_answer, msg_id, sources, suggestions)
            st.rerun()

        except Exception as e:
            st.error(f"Error: {e}")


# ════════════════════════════════════════
# SOURCES PAGE
# ════════════════════════════════════════
elif nav == "Sources":
    st.markdown("""
        <div class="page-head">
            <div class="page-title">Knowledge Sources</div>
            <div class="page-sub">Upload and manage the documents that power your RAG pipeline.</div>
        </div>
    """, unsafe_allow_html=True)

    all_docs = pipeline.get_all_documents()
    builtin_names = {f.name for f in DOCS_DIR.glob("*.md")}
    builtin_docs  = [d for d in all_docs if d.name in builtin_names]
    user_docs     = [d for d in all_docs if d.name not in builtin_names]

    # ── Built-in docs ─────────────────────────────────────────────────────────
    if builtin_docs:
        st.markdown("<div class='src-lbl' style='margin-bottom:12px'>Built-in Documents</div>", unsafe_allow_html=True)
        for d in builtin_docs:
            ext = d.name.rsplit(".", 1)[-1].upper() if "." in d.name else "DOC"
            left, right = st.columns([10, 1])
            with left:
                st.markdown(f"""
                    <div class="doc-row">
                        <div class="doc-icon">📄</div>
                        <div class="doc-name">{d.name}</div>
                        <div class="doc-ext">{ext}</div>
                    </div>
                """, unsafe_allow_html=True)
            with right:
                if st.button("🗑", key=f"del_builtin_{d.doc_id}", help="Remove from index and delete file"):
                    pipeline.delete_document(d.doc_id)
                    try:
                        (DOCS_DIR / d.name).unlink()
                    except Exception:
                        pass
                    st.rerun()

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ── User uploads ──────────────────────────────────────────────────────────
    st.markdown("<div class='src-lbl' style='margin-bottom:12px'>Upload Documents</div>", unsafe_allow_html=True)

    files = st.file_uploader(
        "Drop files here — PDF, TXT, MD",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
        key=f"up_{st.session_state.uploader_key}",
    )

    if files:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        _, btn_col = st.columns([3, 1])
        with btn_col:
            ingest = st.button("⬆  Ingest", use_container_width=True, type="primary")

        if ingest:
            pb = st.progress(0, text="Starting…")
            for i, f in enumerate(files):
                path = Path(".uploads") / f.name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(f.getbuffer())
                pipeline.ingest(str(path), f.name)
                pb.progress((i + 1) / len(files), text=f"Processing {f.name}…")
            st.success("✓  All documents ingested successfully.")
            st.session_state.uploader_key += 1
            st.rerun()

    if user_docs:
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown("<div class='src-lbl' style='margin-bottom:12px'>Uploaded Documents</div>", unsafe_allow_html=True)
        for d in user_docs:
            ext = d.name.rsplit(".", 1)[-1].upper() if "." in d.name else "DOC"
            left, right = st.columns([10, 1])
            with left:
                st.markdown(f"""
                    <div class="doc-row">
                        <div class="doc-icon">📄</div>
                        <div class="doc-name">{d.name}</div>
                        <div class="doc-ext">{ext}</div>
                    </div>
                """, unsafe_allow_html=True)
            with right:
                if st.button("🗑", key=f"del_{d.doc_id}"):
                    pipeline.delete_document(d.doc_id)
                    st.rerun()

    if not builtin_docs and not user_docs:
        st.markdown("""
            <div class="empty-state">
                <div class="empty-icon">⊞</div>
                <div class="empty-msg">No documents yet — upload your first file above.</div>
            </div>
        """, unsafe_allow_html=True)


# ════════════════════════════════════════
# EXPLORER PAGE
# ════════════════════════════════════════
elif nav == "Explorer":
    st.markdown("""
        <div class="page-head">
            <div class="page-title">Document Explorer</div>
            <div class="page-sub">Browse and search the indexed chunks powering your knowledge base.</div>
        </div>
    """, unsafe_allow_html=True)

    search_col, filter_col = st.columns([3, 1])
    with search_col:
        search_query = st.text_input(
            "Search chunks",
            placeholder="Search by keyword…",
            label_visibility="collapsed",
        )
    with filter_col:
        docs      = pipeline.get_all_documents()
        doc_names = ["All Documents"] + [d.name for d in docs]
        doc_filter = st.selectbox("Filter by document", doc_names, label_visibility="collapsed")

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    all_chunks = bm25_store.search_chunks(search_query, limit=30) if search_query else bm25_store.get_all_chunks()

    if doc_filter != "All Documents":
        all_chunks = [c for c in all_chunks if c.get("doc_name") == doc_filter]

    total_chunks = len(bm25_store.get_all_chunks())
    showing      = len(all_chunks)
    search_note  = f' matching "{search_query}"' if search_query else ""
    st.markdown(
        f"<div class='search-stats'>Showing {showing} of {total_chunks} chunks{search_note}</div>",
        unsafe_allow_html=True,
    )

    if all_chunks:
        page_size   = 15
        total_pages = max(1, (len(all_chunks) + page_size - 1) // page_size)
        if "explorer_page" not in st.session_state:
            st.session_state.explorer_page = 0

        page_chunks = all_chunks[
            st.session_state.explorer_page * page_size
            : (st.session_state.explorer_page + 1) * page_size
        ]

        for chunk in page_chunks:
            page_info       = f"Page {chunk.get('page_number', '—')}" if chunk.get("page_number") else ""
            chunk_id_short  = chunk.get("chunk_id", "")[:8]
            content_preview = chunk.get("content", "")[:400]
            if len(chunk.get("content", "")) > 400:
                content_preview += "…"
            st.markdown(f"""
                <div class="chunk-card">
                    <div class="chunk-meta">
                        <div class="chunk-doc">📄 {chunk.get('doc_name', 'Unknown')}</div>
                        <div class="chunk-page">{page_info}</div>
                        <div class="chunk-id">#{chunk_id_short}</div>
                    </div>
                    <div class="chunk-text">{content_preview}</div>
                </div>
            """, unsafe_allow_html=True)

        if total_pages > 1:
            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            p1, p2, p3 = st.columns([1, 2, 1])
            with p1:
                if st.button("← Previous", disabled=st.session_state.explorer_page == 0):
                    st.session_state.explorer_page -= 1
                    st.rerun()
            with p2:
                st.markdown(
                    f"<div style='text-align:center;font-size:0.78rem;color:var(--t3);padding:8px 0'>"
                    f"Page {st.session_state.explorer_page + 1} of {total_pages}</div>",
                    unsafe_allow_html=True,
                )
            with p3:
                if st.button("Next →", disabled=st.session_state.explorer_page >= total_pages - 1):
                    st.session_state.explorer_page += 1
                    st.rerun()
    else:
        st.markdown("""
            <div class="empty-state">
                <div class="empty-icon">⬡</div>
                <div class="empty-msg">No chunks found. Upload and ingest documents first.</div>
            </div>
        """, unsafe_allow_html=True)


# ════════════════════════════════════════
# ANALYTICS PAGE
# ════════════════════════════════════════
elif nav == "Analytics":
    st.markdown("""
        <div class="page-head">
            <div class="page-title">Performance</div>
            <div class="page-sub">RAGAS evaluation metrics, feedback analytics, and query intelligence.</div>
        </div>
    """, unsafe_allow_html=True)

    res     = evaluator.get_analytics()
    fb_data = feedback_mgr.get_analytics()

    if res and res.get("total_evaluations", 0) > 0:

        k1, k2, k3, k4, k5 = st.columns(5)
        kpis = [
            ("Total Queries",  str(res["total_evaluations"]),                                        ""),
            ("Faithfulness",   f"{int(res['avg_faithfulness'] * 100)}%" if res.get('avg_faithfulness') is not None and not (res.get('avg_faithfulness') != res.get('avg_faithfulness')) else "—", "green"),
            ("Relevance",      f"{int(res['avg_relevancy']    * 100)}%" if res.get('avg_relevancy') is not None and not (res.get('avg_relevancy') != res.get('avg_relevancy')) else "—", ""),
            ("Precision",      f"{int(res['avg_precision']    * 100)}%" if res.get('avg_precision') is not None and not (res.get('avg_precision') != res.get('avg_precision')) else "—", "cyan"),
            ("Satisfaction",   f"{int(fb_data['satisfaction_rate'] * 100)}%" if fb_data.get("total", 0) > 0 and not (fb_data.get('satisfaction_rate') != fb_data.get('satisfaction_rate')) else "—", "amber"),
        ]
        for col, (lbl, val, cls) in zip([k1, k2, k3, k4, k5], kpis):
            with col:
                st.markdown(f"""
                    <div class="kpi-card {cls}">
                        <div class="kpi-lbl">{lbl}</div>
                        <div class="kpi-val">{val}</div>
                    </div>
                """, unsafe_allow_html=True)

        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

        tab1, tab2 = st.tabs(["📊 Score Trends", "💬 Feedback"])

        with tab1:
            scores_log = evaluator._scores_log or []
            if len(scores_log) >= 2:
                import pandas as pd
                chart_data = pd.DataFrame([{
                    "Query #":     i + 1,
                    "Faithfulness": e.get("faithfulness", 0),
                    "Relevancy":    e.get("answer_relevancy", 0),
                    "Precision":    e.get("context_precision", 0),
                } for i, e in enumerate(scores_log)])

                st.markdown("<div class='chart-title'>RAGAS Score Trends Over Queries</div>", unsafe_allow_html=True)
                st.line_chart(
                    chart_data.set_index("Query #"),
                    color=["#3E7472", "#059669", "#0E7490"],
                    height=300,
                )

                st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
                st.markdown("<div class='chart-title'>Per-Query Overall Score</div>", unsafe_allow_html=True)
                overall_data = pd.DataFrame({
                    "Query #": range(1, len(scores_log) + 1),
                    "Overall": [s.get("overall", 0) for s in scores_log],
                })
                st.bar_chart(overall_data.set_index("Query #"), color="#3E7472", height=250)
            else:
                st.markdown("""
                    <div class="empty-state" style="padding:40px 0">
                        <div class="empty-icon">📊</div>
                        <div class="empty-msg">Need at least 2 queries to show trend charts.</div>
                    </div>
                """, unsafe_allow_html=True)

        with tab2:
            if fb_data["total"] > 0:
                pos_pct = round(fb_data["positive"] / fb_data["total"] * 100)
                neg_pct = 100 - pos_pct
                st.markdown(f"""
                    <div class="panel">
                        <div class="panel-title">Feedback Distribution</div>
                        <div class="fb-stat">
                            <div class="fb-label">👍 Helpful</div>
                            <div class="fb-bar-bg">
                                <div class="fb-bar-fill pos" style="width:{pos_pct}%"></div>
                            </div>
                            <div class="fb-pct">{fb_data['positive']} ({pos_pct}%)</div>
                        </div>
                        <div class="fb-stat">
                            <div class="fb-label">👎 Flagged</div>
                            <div class="fb-bar-bg">
                                <div class="fb-bar-fill neg" style="width:{neg_pct}%"></div>
                            </div>
                            <div class="fb-pct">{fb_data['negative']} ({neg_pct}%)</div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)

                if fb_data["recent_negative_comments"]:
                    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
                    neg_inner = ""
                    for comment in fb_data["recent_negative_comments"]:
                        ts = comment.get("timestamp", "")[:10]
                        neg_inner += (
                            f'<div class="gap-card">'
                            f'<div class="gap-lbl">⚠ {ts}</div>'
                            f'<div class="gap-q">{comment.get("comment", "No comment")}</div>'
                            f'</div>'
                        )
                    st.markdown(f"""
                        <div class="panel">
                            <div class="panel-title">Recent Negative Feedback</div>
                            {neg_inner}
                        </div>
                    """, unsafe_allow_html=True)
            else:
                st.markdown("""
                    <div class="empty-state" style="padding:40px 0">
                        <div class="empty-icon">💬</div>
                        <div class="empty-msg">No feedback data yet. Use 👍/👎 buttons on answers.</div>
                    </div>
                """, unsafe_allow_html=True)

        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

        # Recent Query History
        logs  = (evaluator._scores_log or [])[-5:]
        inner = ""
        for entry in reversed(logs):
            ts    = entry.get("timestamp", "—")[:10]
            q     = entry.get("question", "—")
            score = entry.get("overall", 0)
            sc    = "var(--green)" if score >= 0.7 else "var(--amber)" if score >= 0.4 else "var(--red)"
            score_pct = f"{int(score*100)}%" if score is not None and not (score != score) else "—"
            inner += (
                f'<div class="log-card">'
                f'<div class="log-date">{ts} · <span style="color:{sc};font-weight:600">{score_pct}</span></div>'
                f'<div class="log-q">{q}</div></div>'
            )
        if not inner:
            inner = "<div style='color:var(--t3);font-size:.855rem;padding:8px 0'>No queries yet.</div>"
        st.markdown(f"""
            <div class="panel">
                <div class="panel-title">Recent Query History</div>
                {inner}
            </div>
        """, unsafe_allow_html=True)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        # Knowledge Gaps
        gaps  = res.get("knowledge_gaps", [])
        inner = ""
        for gap in reversed(gaps):
            inner += (
                f'<div class="gap-card">'
                f'<div class="gap-lbl">⚠ Low confidence</div>'
                f'<div class="gap-q">{gap}</div></div>'
            )
        if not inner:
            inner = "<div class='ok-state'><div class='ok-icon'>✓</div><div class='ok-msg'>No knowledge gaps detected</div></div>"
        st.markdown(f"""
            <div class="panel">
                <div class="panel-title">Knowledge Gaps</div>
                {inner}
            </div>
        """, unsafe_allow_html=True)

    else:
        st.markdown("""
            <div class="empty-state" style="padding:80px 0">
                <div class="empty-icon" style="font-size:2.2rem">◎</div>
                <div style="font-size:0.95rem;color:var(--t2);font-weight:500;margin-top:4px">No evaluation data yet.</div>
                <div style="font-size:0.82rem;color:var(--t3);margin-top:6px">Start asking questions to generate performance metrics.</div>
            </div>
        """, unsafe_allow_html=True)

# ════════════════════════════════════════
# RECENTS PAGE
# ════════════════════════════════════════
elif nav == "Recents":
    head_col, clear_col = st.columns([8, 2])
    with head_col:
        st.markdown("""
            <div class="page-head">
                <div class="page-title">Recent Conversations</div>
                <div class="page-sub">Pick up where you left off.</div>
            </div>
        """, unsafe_allow_html=True)
    with clear_col:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("🗑  Clear All", use_container_width=True):
            clear_all_conversations()
            st.rerun()

    recent_sessions = session_manager.list_sessions(limit=20)
    if recent_sessions:
        for session in recent_sessions:
            first_user = next(
                (m.content for m in session.messages if m.role == MessageRole.USER),
                "Untitled conversation",
            )
            title = first_user[:60] + ("…" if len(first_user) > 60 else "")
            ts = session.messages[-1].timestamp.strftime("%b %d, %Y · %H:%M") if session.messages else "—"
            msg_count = len([m for m in session.messages if m.role == MessageRole.USER])
            left, right = st.columns([10, 1])
            with left:
                st.markdown(f"""
                    <div class="doc-row">
                        <div class="doc-icon">◈</div>
                        <div class="doc-name">{title}</div>
                        <div class="doc-ext">{msg_count}Q · {ts}</div>
                    </div>
                """, unsafe_allow_html=True)
            with right:
                if st.button("→", key=f"open_{session.session_id}", use_container_width=True):
                    switch_conversation(session.session_id)
                    st.rerun()
    else:
        st.markdown("""
            <div class="empty-state">
                <div class="empty-icon">◷</div>
                <div class="empty-msg">No recent conversations yet.</div>
            </div>
        """, unsafe_allow_html=True)