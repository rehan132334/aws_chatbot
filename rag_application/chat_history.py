


#docker exec -it local-postgres psql -U postgres -d postgres -c "TRUNCATE TABLE chat_history, session_metadata RESTART IDENTITY;"TRUNCATE TABL
import os
from state import model
import psycopg
from promt import session_title_system_prompt
DB_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5433/postgres")
TABLE_NAME = "chat_history"


from pydantic import BaseModel, Field

class SessionTitle(BaseModel):
    title: str = Field(description="A concise 4-5 word title for the chat session. No markdown, no punctuation beyond spaces.")

title_model = model.with_structured_output(SessionTitle)
def list_previous_sessions(conn, table_name=TABLE_NAME):
    """
    Returns a list of tuples: (session_id, session_title)
    Derives the title from the user's initial prompt in that session.
    """
    try:
        with conn.cursor() as cur:
            # Fetches session_id and the very first message content for each session
            cur.execute(f"""
                SELECT DISTINCT ON (session_id) session_id::TEXT, message->>'content' AS title
                FROM {table_name}
                ORDER BY session_id, id ASC
            """)
            sessions = cur.fetchall()
            return sessions
    except Exception as e:
        print(f"Error retrieving previous sessions: {e}")
        return []

def generate_title(user_query: str) -> str:
    '''Generates a concise title for the session based on the user's initial query.'''
    try:
        response = title_model.invoke(session_title_system_prompt.format(query=user_query))
        print(f"Generated session title: {response.title}")
        return response.title
    except Exception as e:
        print(f"Error generating session title: {e}")
        return "Untitled Session"

def save_session_title(conn, session_id: str, title: str):
    """Saves or updates a session title in the session_metadata table."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS session_metadata (
                    session_id VARCHAR(255) PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """);
            cur.execute("""
                INSERT INTO session_metadata (session_id, title)
                VALUES (%s, %s)
                ON CONFLICT (session_id) DO UPDATE SET title = EXCLUDED.title;
            """, (str(session_id), title))
    except Exception as e:
        print(f"Error saving session title: {e}")
def list_previous_sessions(conn, table_name=TABLE_NAME):
    """Retrieves previous session IDs along with their stored titles from session_metadata."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.session_id, m.title
                FROM session_metadata m
                ORDER BY m.created_at DESC
            """)
            return cur.fetchall()
    except Exception as e:
        print(f"Error retrieving previous sessions: {e}")
        return []
