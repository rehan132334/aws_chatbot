from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
import os
import psycopg
import persistance_memo
from dotenv import load_dotenv
from typing import Literal
import os
from chat_history import DB_URL
import psycopg
from langchain_community.chat_message_histories import DynamoDBChatMessageHistory
from langchain_postgres import PostgresChatMessageHistory
from state import RAGConfig,model

from promt import memory_system_promt
load_dotenv()  # Load environment variables from .env file
from promt import personal_memo_system_prompt
class PersonalMemo(BaseModel):
    is_personal: bool = Field(
        description="True if the user query contains personal details, identity facts, or preferences, otherwise False."
    )
conn = psycopg.connect(DB_URL,autocommit=True)


model= model.with_structured_output(PersonalMemo)
def check_personal_info(user_query:str)->PersonalMemo:
    """Checks if the user's query contains personal information."""
    all_personal_memos = persistance_memo.get_all_personal_memos(conn, TABLE_NAME_2)
    response = model.invoke(personal_memo_system_prompt.format(query=user_query, previous_data=all_personal_memos))
    return response 

DB_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5433/postgres")
TABLE_NAME_2 = "PERSONAL_MEMO" 



