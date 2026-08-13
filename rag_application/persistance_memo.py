import os
import psycopg
from langchain_community.chat_message_histories import DynamoDBChatMessageHistory
from langchain_postgres import PostgresChatMessageHistory
from state import RAGConfig,model

from promt import memory_system_promt
import tiktoken
Max_tokens=2000


def get_token_count(messages: list[str])->int:
    """Returns the number of tokens in a given text using tiktoken."""
    encoding = tiktoken.get_encoding("cl100k_base")
    total_tokens=0
    for msg in messages:
        text = msg.content if hasattr(msg, "content") else str(msg)
        total_tokens += len(encoding.encode(text)) + 4
    return total_tokens


def init_postgres_history_table(conn: psycopg.Connection, table_name: str):
    """Call this once at startup to ensure the table exists."""
    try:
        PostgresChatMessageHistory.create_tables(conn, table_name)
        print(f"Table '{table_name}' is ready.")
        return True
    except Exception as e:
        print(f"Failed to initialize table '{table_name}': {e}")
        return False


def get_postgres_history(conn: psycopg.Connection, table_name: str, session_id: str, keep_last_n: int = 1) -> list[str]:
    """Retrieves previous messages for the given session_id from PostgreSQL."""
    try:
        session_id=str(session_id)
        history = PostgresChatMessageHistory(
            table_name,
            session_id,
            sync_connection=conn
        )
        messages = history.messages
        
        total_tokens=get_token_count(messages)
        if(total_tokens>Max_tokens and len(messages)>keep_last_n):
            older_messages = messages[:-keep_last_n]
            recent_messages = messages[-keep_last_n:]
            formatted_older_history = "\n".join(
                f"{msg.type.upper()}: {msg.content}" for msg in older_messages
            )
            response = model.invoke(
                memory_system_promt.format(messages=formatted_older_history)
            )
            summary_str = f"SYSTEM SUMMARY OF PRIOR CONVERSATION: {response.content}"

            formatted_recent = [f"{msg.type}: {msg.content}" for msg in recent_messages]

           
            return [summary_str] + formatted_recent

        
        return [f"{msg.type}: {msg.content}" for msg in messages]
            
    except Exception as e:
        print(f"PostgreSQL Memory Warning: {e}")
        return []


def save_to_postgres_history(conn: psycopg.Connection, table_name: str, session_id: str, user_query: str, ai_response: str):
    """Appends user query and AI response to PostgreSQL for the given session_id."""
    try:
        session_id=str(session_id)
        history = PostgresChatMessageHistory(
            table_name,
            session_id,
            sync_connection=conn
        )
        history.add_user_message(user_query)
        history.add_ai_message(ai_response)
    except Exception as e:
        print(f"PostgreSQL Save Warning: {e}")



def get_recent_messages_preview(conn: psycopg.Connection, table_name: str, session_id: str, limit: int = 5) -> list[tuple[str, str]]:
    """Fetches the last N messages as (role, content) tuples for display on session load."""
    try:
        session_id=str(session_id)
        history = PostgresChatMessageHistory(
            table_name,
            session_id,
            sync_connection=conn
        )
        messages = history.messages[-limit:]
        
        preview = []
        for msg in messages:
            role = "User" if msg.type == "human" else "AI"
            preview.append((role, msg.content))
        return preview
    except Exception as e:
        print(f"Error fetching preview messages: {e}")
        return []

def get_all_personal_memos(conn, table_name="PERSONAL_MEMO", limit_per_session: int = 5, max_sessions: int = 10) -> list[str]:
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT DISTINCT session_id FROM "{table_name}" ORDER BY session_id DESC LIMIT %s;', (max_sessions,))
            session_ids = [r[0] for r in cur.fetchall()]
        memos = []
        for sid in session_ids:
            history = PostgresChatMessageHistory(table_name, str(sid), sync_connection=conn)
            memos.extend(f"{msg.type}: {msg.content}" for msg in history.messages[-limit_per_session:])
        return memos
    except Exception as e:
        print(f"Error fetching global personal memo: {e}")
        return []