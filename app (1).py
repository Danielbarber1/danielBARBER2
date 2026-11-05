import base64
import io
import random
import time
import uuid
from datetime import datetime

import requests
import streamlit as st

# ---------- הגדרות ----------
APP_NAME = "AI VINO"
GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
NUM_SEARCH_RESULTS = 4
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
BUSY_MESSAGE = "השרתים של הבינה המלאכותית עמוסים כרגע. נסה שוב בעוד רגע."

SYSTEM_PROMPT = f"""אתה העוזר של האפליקציה "{APP_NAME}".
ענה בעברית, אלא אם המשתמש כותב בשפה אחרת. היה ברור, מדויק וידידותי.
תשובות קצרות וממוקדות, בלי הקדמות מיותרות. הרחב רק כשהמשתמש מבקש פירוט.
כשמסופקות תוצאות חיפוש, התבסס עליהן והפנה למקורות בסימון [מספר].
אם מסופקת תמונה, תאר ונתח אותה לפי השאלה. אם מסופקת הקלטה קולית, הבן אותה ועבד על התוכן שלה.
אם התוצאות לא מספיקות או סותרות, כתוב זאת במפורש. אל תמציא עובדות."""

st.set_page_config(page_title=APP_NAME, page_icon="🤖", layout="centered", initial_sidebar_state="collapsed")

# ---------- עיצוב ----------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700;800&display=swap');
    html, body, [class*="css"], .stApp { font-family: 'Heebo', system-ui, 'Segoe UI', Arial, sans-serif; }
    .stApp {
        background:
            radial-gradient(1000px 500px at 85% -10%, rgba(124,58,237,.20), transparent 60%),
            radial-gradient(800px 500px at -10% 110%, rgba(6,182,212,.14), transparent 60%),
            #0b0b14;
    }
    .block-container { max-width: 860px; padding-top: 2.2rem; padding-bottom: 6rem; }
    #MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }
    .brand {
        font-size: 2.6rem; font-weight: 800; text-align: center; letter-spacing: -0.5px;
        background: linear-gradient(90deg, #a78bfa, #7c3aed 40%, #06b6d4);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: .2rem;
    }
    .subtitle { text-align: center; color: #94a3b8; margin-bottom: 1.8rem; font-size: 1.02rem; }
    [data-testid="stChatMessage"] {
        border-radius: 18px; padding: .9rem 1.1rem; margin-bottom: .8rem;
        background: rgba(22,22,38,.78); border: 1px solid rgba(124,58,237,.18);
        box-shadow: 0 8px 24px rgba(0,0,0,.25); line-height: 1.75; color: #e8eaf3;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background: linear-gradient(135deg, rgba(124,58,237,.35), rgba(6,182,212,.18));
        border: 1px solid rgba(167,139,250,.35);
    }
    [data-testid="stChatMessage"] a { color: #67e8f9; text-decoration: none; }
    [data-testid="stChatInput"] {
        background: rgba(19,19,31,.92); border: 1px solid rgba(124,58,237,.35);
        border-radius: 16px; box-shadow: 0 0 0 4px rgba(124,58,237,.08);
    }
    [data-testid="stChatInput"]:focus-within { border-color: #7c3aed; box-shadow: 0 0 0 4px rgba(124,58,237,.22); }
    [data-testid="stChatInput"] textarea { color: #eef0f7 !important; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg,#13131f 0%,#0d0d18 100%); border-left: 1px solid rgba(124,58,237,.2); }
    [data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarCollapseButton"] button {
        background: rgba(124,58,237,.18); border: 1px solid rgba(124,58,237,.5); border-radius: 10px; color: #eef0f7;
    }
    .stButton > button {
        border-radius: 12px; border: 1px solid rgba(124,58,237,.45); background: rgba(124,58,237,.12);
        color: #eef0f7; font-weight: 600; transition: all .2s ease;
    }
    .stButton > button:hover {
        border-color: #a78bfa; background: linear-gradient(90deg,#7c3aed,#06b6d4); color: #fff;
        transform: translateY(-1px); box-shadow: 0 6px 18px rgba(124,58,237,.35);
    }
    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-thumb { background: rgba(124,58,237,.35); border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


# ---------- מפתחות והגדרות ----------
def get_secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default) or default
    except Exception:
        return default


GEMINI_KEY = get_secret("GEMINI_API_KEY")
TAVILY_KEY = get_secret("TAVILY_API_KEY")
ADMIN_EMAIL = get_secret("ADMIN_EMAIL").strip().lower()
# REQUIRE_LOGIN = "true" -> דורש התחברות עם Google. אחרת האפליקציה פתוחה בלי התחברות.
REQUIRE_LOGIN = get_secret("REQUIRE_LOGIN", "false").strip().lower() == "true"


# ---------- התחברות עם Google ----------
def require_admin_login() -> None:
    """מציג מסך התחברות. נכנסים רק אם המייל תואם ל-ADMIN_EMAIL. לכל השאר אין גישה."""
    if not hasattr(st, "login"):
        st.error("גרסת Streamlit ישנה מדי. עדכן ל-streamlit>=1.44 ב-requirements.txt.")
        st.stop()
    if not ADMIN_EMAIL:
        st.error("חסר ADMIN_EMAIL ב-Secrets.")
        st.stop()

    if not st.user.is_logged_in:
        st.markdown(f'<div class="brand">{APP_NAME}</div>', unsafe_allow_html=True)
        st.markdown('<div class="subtitle">התחבר עם חשבון Google כדי להמשיך</div>', unsafe_allow_html=True)
        if st.button("התחברות עם Google", use_container_width=True, type="primary"):
            st.login("google")
        st.stop()

    email = (st.user.email or "").strip().lower()
    if email != ADMIN_EMAIL:
        st.error("אין לך הרשאה לאפליקציה הזו.")
        if st.button("התנתק"):
            st.logout()
        st.stop()


if REQUIRE_LOGIN:
    require_admin_login()

if not GEMINI_KEY:
    st.error("חסר GEMINI_API_KEY ב-Secrets.")
    st.stop()


# ---------- לוג פעילות (נשמר בזיכרון השרת, מתאפס בהפעלה מחדש) ----------
@st.cache_resource
def activity_log() -> list[dict]:
    return []


def log_event(kind: str, detail: str) -> None:
    activity_log().append(
        {"time": datetime.now().strftime("%d/%m %H:%M:%S"), "type": kind, "detail": detail[:120]}
    )


# ---------- ניהול שיחות (session_state) ----------
def new_chat() -> None:
    chat_id = uuid.uuid4().hex[:8]
    st.session_state.chats[chat_id] = {"title": "שיחה חדשה", "messages": []}
    st.session_state.current_id = chat_id


if "chats" not in st.session_state:
    st.session_state.chats = {}
    st.session_state.current_id = None
if st.session_state.current_id not in st.session_state.chats:
    new_chat()


# ---------- עזרי מדיה ----------
def to_inline_part(data: bytes, mime_type: str) -> dict:
    return {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(data).decode()}}


def search_web(query: str) -> list[dict]:
    if not TAVILY_KEY:
        return []
    resp = requests.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {TAVILY_KEY}"},
        json={"query": query, "max_results": NUM_SEARCH_RESULTS, "search_depth": "basic"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def build_context(results: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] {r.get('title', '')}\nURL: {r.get('url', '')}\n{r.get('content', '')}"
        for i, r in enumerate(results, 1)
    )


def format_sources(results: list[dict]) -> str:
    if not results:
        return ""
    return "**מקורות:** " + " | ".join(f"[{i}]({r['url']})" for i, r in enumerate(results, 1))


# ---------- Gemini עם ניסיון חוזר ----------
class GeminiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def ask_gemini(history: list[dict], max_attempts: int = 8, base_delay: float = 2.0, max_delay: float = 20.0) -> str:
    """history: רשימת הודעות עם role ('user' / 'assistant') ו-parts (רשימת חלקים)."""
    for attempt in range(1, max_attempts + 1):
        try:
            return _ask_gemini_once(history)
        except GeminiError as e:
            if e.status not in RETRYABLE_STATUS or attempt == max_attempts:
                raise
        except requests.RequestException:
            if attempt == max_attempts:
                raise
        wait = min(base_delay * (2 ** (attempt - 1)), max_delay)
        time.sleep(wait + random.uniform(0, 1))
    raise RuntimeError("נכשל אחרי מספר ניסיונות")


def _ask_gemini_once(history: list[dict]) -> str:
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": m["parts"]}
        for m in history
    ]
    resp = requests.post(
        GEMINI_URL,
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY},
        json={
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.4, "topP": 0.9},
        },
        timeout=90,
    )
    if not resp.ok:
        raise GeminiError(resp.status_code, f"Gemini {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    candidate = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
    if not text:
        reason = candidate.get("finishReason") or data.get("promptFeedback", {}).get("blockReason", "לא ידועה")
        raise RuntimeError(f"התשובה ריקה או נחסמה (סיבה: {reason})")
    return text


def text_to_speech(text: str) -> bytes | None:
    """הקראת התשובה דרך gTTS (חינם). מחזיר None אם לא זמין."""
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        gTTS(text=text[:1500], lang="iw").write_to_fp(buf)
        return buf.getvalue()
    except Exception:
        return None


# ---------- סרגל צד ----------
with st.sidebar:
    st.markdown(f"## 🤖 {APP_NAME}")
    if REQUIRE_LOGIN:
        st.caption(f"מחובר: {st.user.email}")
    page = st.radio("מסך", ["💬 צ'אט", "🛠️ ניהול"], label_visibility="collapsed")
    if REQUIRE_LOGIN and st.button("🚪 התנתק", use_container_width=True):
        st.logout()

    if page == "💬 צ'אט":
        if st.button("➕ שיחה חדשה", use_container_width=True, type="primary"):
            new_chat()
            st.rerun()
        use_search = st.toggle("חיפוש ברשת", value=bool(TAVILY_KEY), disabled=not TAVILY_KEY)
        speak_answers = st.toggle("הקרא תשובות בקול", value=False)
        st.divider()
        st.markdown("**היסטוריית שיחות**")
        for cid in reversed(list(st.session_state.chats.keys())):
            chat = st.session_state.chats[cid]
            marker = "● " if cid == st.session_state.current_id else ""
            col_open, col_del = st.columns([5, 1])
            if col_open.button(marker + chat["title"], key=f"open_{cid}", use_container_width=True):
                st.session_state.current_id = cid
                st.rerun()
            if col_del.button("🗑", key=f"del_{cid}"):
                del st.session_state.chats[cid]
                if cid == st.session_state.current_id:
                    st.session_state.current_id = None
                st.rerun()
    else:
        use_search, speak_answers = bool(TAVILY_KEY), False

# ---------- תוכן ראשי ----------
if page == "🛠️ ניהול":
    st.markdown('<div class="brand">ניהול</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">פעילות אחרונה באפליקציה</div>', unsafe_allow_html=True)
    events = list(reversed(activity_log()))
    total_chats = len(st.session_state.chats)
    total_msgs = sum(len(c["messages"]) for c in st.session_state.chats.values())
    c1, c2, c3 = st.columns(3)
    c1.metric("בקשות שנשלחו", len(events))
    c2.metric("שיחות פתוחות אצלך", total_chats)
    c3.metric("הודעות בשיחות", total_msgs)
    st.divider()
    if events:
        st.dataframe(events, use_container_width=True, hide_index=True)
    else:
        st.info("עדיין אין פעילות.")
    st.caption("הלוג מתאפס בכל הפעלה מחדש של השרת. לשמירה קבועה צריך מסד נתונים.")
    st.stop()

current = st.session_state.chats[st.session_state.current_id]

st.markdown(f'<div class="brand">{APP_NAME}</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">שאל בטקסט, שלח תמונה או הקלט הודעה קולית</div>', unsafe_allow_html=True)

for msg in current["messages"]:
    with st.chat_message(msg["role"]):
        if msg.get("image_bytes"):
            st.image(msg["image_bytes"], width=280)
        st.markdown(msg["content"])
        if msg.get("sources"):
            st.markdown(msg["sources"])
        if msg.get("audio_answer"):
            st.audio(msg["audio_answer"], format="audio/mp3")

# ---------- קלט: תמונה והקלטה קולית ----------
with st.expander("📎 צירוף תמונה או הקלטה קולית"):
    uploaded_image = st.file_uploader("תמונה", type=["png", "jpg", "jpeg", "webp"], key="img_upload")
    recorded_audio = st.audio_input("הקלט הודעה קולית", key="voice_input")
    send_voice = st.button("שלח הקלטה", disabled=recorded_audio is None)

typed_prompt = st.chat_input("כתוב שאלה...")
prompt = typed_prompt or (
    "(הודעה קולית)" if send_voice and recorded_audio is not None else None
)

if prompt:
    parts_now: list[dict] = []
    image_bytes = None
    if uploaded_image is not None:
        image_bytes = uploaded_image.getvalue()
        parts_now.append(to_inline_part(image_bytes, uploaded_image.type or "image/png"))
    if send_voice and recorded_audio is not None and not typed_prompt:
        parts_now.append(to_inline_part(recorded_audio.getvalue(), "audio/wav"))

    if not current["messages"]:
        current["title"] = prompt[:30] + ("…" if len(prompt) > 30 else "")

    user_text = prompt if typed_prompt else "הבן את ההקלטה הקולית ועבד על התוכן שלה."
    text_for_model = user_text

    results = []
    t_search = 0.0
    if typed_prompt and use_search and TAVILY_KEY:
        with st.spinner("מחפש ברשת..."):
            t0 = time.perf_counter()
            try:
                results = search_web(typed_prompt)
            except Exception:
                results = []
            t_search = time.perf_counter() - t0
    if results:
        text_for_model += f"\n\nתוצאות חיפוש עדכניות:\n{build_context(results)}"

    parts_now.insert(0, {"text": text_for_model})

    display_text = prompt
    current["messages"].append({"role": "user", "content": display_text, "image_bytes": image_bytes})
    with st.chat_message("user"):
        if image_bytes:
            st.image(image_bytes, width=280)
        st.markdown(display_text)

    # היסטוריה למודל: טקסט בלבד מההודעות הקודמות שלא נכשלו, ואז ההודעה הנוכחית עם המדיה
    history = [
        {"role": m["role"], "parts": [{"text": m["content"]}]}
        for m in current["messages"][:-1]
        if not m.get("error")
    ]
    history.append({"role": "user", "parts": parts_now})

    log_event("chat", display_text)
    sources = format_sources(results)
    with st.chat_message("assistant"):
        is_error = False
        t_model_start = time.perf_counter()
        with st.spinner("כותב תשובה..."):
            try:
                answer = ask_gemini(history)
            except GeminiError as e:
                is_error = True
                answer = BUSY_MESSAGE if e.status in RETRYABLE_STATUS else f"הייתה שגיאה בקבלת התשובה: {e}"
            except Exception as e:
                is_error = True
                answer = BUSY_MESSAGE if isinstance(e, requests.RequestException) else f"הייתה שגיאה: {e}"
        t_model = time.perf_counter() - t_model_start
        st.markdown(answer)
        if sources and not is_error:
            st.markdown(sources)
        timing = f"⏱ מודל: {t_model:.1f} שנ'"
        if t_search:
            timing = f"⏱ חיפוש: {t_search:.1f} שנ' | " + timing
        st.caption(timing)

        audio_answer = None
        if speak_answers and not is_error:
            audio_answer = text_to_speech(answer)
            if audio_answer:
                st.audio(audio_answer, format="audio/mp3")

    current["messages"].append(
        {
            "role": "assistant",
            "content": answer,
            "sources": "" if is_error else sources,
            "error": is_error,
            "audio_answer": audio_answer,
        }
    )
