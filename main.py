import uuid
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg
from dotenv import load_dotenv

load_dotenv()

from rag_application.chat_history import (
    list_previous_sessions, DB_URL, TABLE_NAME,
    generate_title, save_session_title
)
from rag_application.persistance_memo import (
    init_postgres_history_table, get_postgres_history,
    save_to_postgres_history, get_recent_messages_preview,
    get_all_personal_memos
)
from rag_application.personal_memo import check_personal_info, TABLE_NAME_2
from rag_application.rag import app as langgraph_app
from rag_application.file_extractor import extract_text

# ---------------------------------------------------------
# LIFESPAN HANDLER (Model & Database Warmup)
# ---------------------------------------------------------
conn = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global conn
    # Initialize DB Connections & Tables
    conn = psycopg.connect(DB_URL, autocommit=True)
    init_postgres_history_table(conn, TABLE_NAME)
    init_postgres_history_table(conn, TABLE_NAME_2)

    # FIX: Create session_metadata table (was missing!)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_metadata (
            session_id VARCHAR PRIMARY KEY,
            title VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    print("✅ Postgres DB initialized & ready.")
    yield
    # Cleanup on shutdown
    if conn:
        conn.close()
        print("🛑 DB Connection closed.")

app = FastAPI(title="AWS Architect AI API", version="1.0", lifespan=lifespan)

# Allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# PYDANTIC SCHEMAS
# ---------------------------------------------------------
class ChatResponse(BaseModel):
    session_id: str
    response: str
    is_personal_saved: bool
    failed_files: list[str] = []

class SessionResponse(BaseModel):
    session_id: str
    title: str

# ---------------------------------------------------------
# ENDPOINTS
# ---------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok", "db_connected": conn is not None}

@app.get("/sessions", response_model=list[SessionResponse])
def get_sessions():
    """Retrieve all past chat sessions."""
    sessions = list_previous_sessions(conn, TABLE_NAME)
    return [{"session_id": sid, "title": title or "Untitled Session"} for sid, title in sessions]

@app.get("/sessions/{session_id}/history")
def get_session_history(session_id: str, limit: int = 10):
    """Fetch history preview for a specific session."""
    recent_msgs = get_recent_messages_preview(conn, TABLE_NAME, session_id, limit=limit)
    return [{"role": role, "content": content} for role, content in recent_msgs]

# FIX: Changed from JSON body to Form + File upload
@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(
    session_id: str = Form(None),
    query: str = Form(...),
    files: list[UploadFile] = File(None)
):
    """Main execution route for handling AWS architectural queries."""
    session_id = session_id or str(uuid.uuid4())
    user_query = query

    # FIX: Read uploaded files and append content to query
    file_context = ""
    failed_files = []
    if files:
        for file in files:
            try:
                file_bytes = file.file.read()
                extracted_text = extract_text(file.filename, file_bytes)
                file_context += f"\n\n--- Content from {file.filename} ---\n{extracted_text}"
            except Exception as e:
                print(f"Warning: Could not read file {file.filename}: {e}")
                failed_files.append(file.filename)

    if file_context:
        user_query = user_query + "\n\n" + file_context

    if failed_files:
        failed_list = ", ".join(failed_files)
        # Tell the model so it can mention this to the user, instead of the
        # failure only ever showing up in server logs.
        user_query += (
            f"\n\n[SYSTEM NOTE: The following uploaded file(s) could not be read "
            f"and were NOT included above — mention this to the user: {failed_list}]"
        )
    # 1. Fetch History & Context
    history_result = get_postgres_history(conn, TABLE_NAME, session_id=session_id)

    # 2. Generate title on new session
    if not history_result:
        title = generate_title(user_query)
        save_session_title(conn, session_id, title)

    all_personal_memos = get_all_personal_memos(conn, TABLE_NAME_2)

    # 3. Construct Graph Input State
    input_state = {
        "query": user_query,
        "message": "",
        "message_history": history_result,
        "Personal_info": all_personal_memos,
        "max_iterations": 0,
        "is_correct": False,
        "error_message": "",
        "response": ""
    }

    # 4. Invoke LangGraph
    try:
        result = langgraph_app.invoke(input_state)
        ai_response = result.get("response", "No response generated.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent Execution Error: {str(e)}")

    # 5. Check & Save Personal Memos
    is_personal_saved = False
    try:
        if check_personal_info(user_query).is_personal:
            save_to_postgres_history(
                conn, TABLE_NAME_2, session_id=session_id, user_query=user_query, ai_response=ai_response
            )
            is_personal_saved = True
    except Exception as e:
        print(f"Warning: Personal info check failed: {e}")

    # 6. Save Chat History
    save_to_postgres_history(
        conn, TABLE_NAME, session_id=session_id, user_query=user_query, ai_response=ai_response
    )

    return ChatResponse(
        session_id=session_id,
        response=ai_response,
        is_personal_saved=is_personal_saved
    )