from pydantic import BaseModel, Field
from groq import BadRequestError
import os
import psycopg
import persistance_memo
from dotenv import load_dotenv
from chat_history import DB_URL
from state import RAGConfig, model as base_model
from promt import personal_memo_system_prompt

load_dotenv()

class PersonalMemo(BaseModel):
    is_personal: bool = Field(
        description="True if the user query contains personal details, identity facts, or preferences, otherwise False."
    )

conn = psycopg.connect(DB_URL, autocommit=True)
DB_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5433/postgres")
TABLE_NAME_2 = "PERSONAL_MEMO"

structured_model = base_model.with_structured_output(PersonalMemo)

def check_personal_info(user_query: str) -> PersonalMemo:
    """Checks if the user's query contains personal information."""
    all_personal_memos = persistance_memo.get_all_personal_memos(conn, TABLE_NAME_2)
    prompt = personal_memo_system_prompt.format(query=user_query, previous_data=all_personal_memos)
    try:
        return structured_model.invoke(prompt)
    except BadRequestError as e:
        if "tool_use_failed" in str(e):
            # Model answered the query instead of classifying it — fall back
            # to a plain yes/no ask on the unstructured base model.
            fallback = base_model.invoke(
                prompt + '\n\nDo not answer the user input. Respond with exactly one word: "true" or "false".'
            )
            return PersonalMemo(is_personal="true" in fallback.content.strip().lower())
        raise