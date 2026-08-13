import streamlit as st
import requests
import uuid
import os

st.set_page_config(page_title="AWS Architect AI", page_icon="☁️", layout="wide")

# URL of your FastAPI backend
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

# ───────────────────────────────────────────────
# SESSION STATE INITIALIZATION
# ───────────────────────────────────────────────
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "sessions" not in st.session_state:
    st.session_state.sessions = []
if "file_uploader_key" not in st.session_state:
    st.session_state.file_uploader_key = 0

# Fetch active sessions from FastAPI
def load_sessions():
    try:
        res = requests.get(f"{BACKEND_URL}/sessions")
        if res.status_code == 200:
            st.session_state.sessions = res.json()
    except Exception as e:
        st.sidebar.error(f"Failed to connect to backend: {e}")

load_sessions()

# ───────────────────────────────────────────────
# SIDEBAR
# ───────────────────────────────────────────────
st.sidebar.title("☁️ AWS Architect AI")

if st.sidebar.button("➕ New Chat", use_container_width=True):
    st.session_state.current_session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.file_uploader_key += 1
    st.rerun()

st.sidebar.subheader("Recent Chats")
for sess in st.session_state.sessions:
    sid = sess["session_id"]
    title = sess["title"]

    if st.sidebar.button(f"💬 {title[:25]}", key=sid, use_container_width=True):
        st.session_state.current_session_id = sid
        res = requests.get(f"{BACKEND_URL}/sessions/{sid}/history")
        if res.status_code == 200:
            st.session_state.messages = [
                {"role": "user" if m["role"] == "User" else "assistant", "content": m["content"]}
                for m in res.json()
            ]
        st.rerun()

# ───────────────────────────────────────────────
# MAIN CHAT AREA
# ───────────────────────────────────────────────
st.title("☁️ AWS Architect AI")

# ═══ NEW: Subtitle note ═══
st.markdown(
    """
    <p style="font-size: 16px; opacity: 0.8; margin-top: -10px; margin-bottom: 25px;">
        📎 Please provide your Project <b>README.md</b>, <b>requirements.txt</b>, or <b>Dockerfile</b> 
        for understanding your project
    </p>
    """,
    unsafe_allow_html=True
)

# ═══ NEW: Drag & Drop File Zone ═══
st.markdown("### 📎 Project Files")

uploaded_files = st.file_uploader(
    "Drag and drop your README.md, requirements.txt, or Dockerfile here — or click to browse",
    type=["md", "txt", "json", "yaml", "yml", "dockerfile"],
    accept_multiple_files=True,
    key=f"file_uploader_{st.session_state.file_uploader_key}"
)

# Show file pill badges when files are selected
if uploaded_files:
    file_badges = "  •  ".join([f"📄 `{f.name}`" for f in uploaded_files])
    st.info(f"**Files attached for your query:** {file_badges}")

st.divider()

# ───────────────────────────────────────────────
# CHAT MESSAGES CONTAINER
# ───────────────────────────────────────────────
chat_container = st.container()
with chat_container:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# ───────────────────────────────────────────────
# CHAT INPUT BAR
# ───────────────────────────────────────────────
user_input = st.chat_input("Ask about your AWS Architecture...")

if user_input:
    display_text = user_input
    if uploaded_files:
        attached_names = ", ".join([f"`{f.name}`" for f in uploaded_files])
        display_text += f"\n\n*(Attached files: {attached_names})*"

    st.session_state.messages.append({"role": "user", "content": display_text})
    with chat_container:
        with st.chat_message("user"):
            st.markdown(display_text)

    with chat_container:
        with st.chat_message("assistant"):
            with st.spinner("Analyzing project files & thinking..."):
                try:
                    data_payload = {
                        "session_id": st.session_state.current_session_id,
                        "query": user_input
                    }

                    files_payload = []
                    if uploaded_files:
                        for uf in uploaded_files:
                            files_payload.append(
                                ("files", (uf.name, uf.getvalue(), uf.type or "text/plain"))
                            )

                    # FIX: Always send as multipart when files exist, plain form otherwise
                    if files_payload:
                        response = requests.post(
                            f"{BACKEND_URL}/chat",
                            data=data_payload,
                            files=files_payload
                        )
                    else:
                        response = requests.post(
                            f"{BACKEND_URL}/chat",
                            data=data_payload
                        )

                    if response.status_code == 200:
                        data = response.json()
                        ai_reply = data.get("response", data.get("output", "Done."))
                        st.markdown(ai_reply)
                        st.session_state.messages.append({"role": "assistant", "content": ai_reply})

                        if data.get("is_personal_saved"):
                            st.toast("💾 Saved personal context to memory", icon="🧠")
                        failed_files = data.get("failed_files") or []
                        if failed_files:
                            st.warning(
                                "⚠️ Couldn't read the following file(s), so they "
                                "were **not** included in your query: "
                                + ", ".join(f"`{f}`" for f in failed_files)
                            )
                        st.session_state.file_uploader_key += 1
                        load_sessions()
                        st.rerun()
                    else:
                        st.error(f"Error {response.status_code}: {response.text}")
                except Exception as e:
                    st.error(f"Failed to reach API server: {e}")