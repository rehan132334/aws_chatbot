import operator
from typing import Annotated, TypedDict
import os
from dotenv import load_dotenv

load_dotenv()
import asyncio


#initiating the model
import os
from openai import OpenAI
import litellm
from langchain_groq import ChatGroq
model = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY"),
)

from typing import Literal  
class RAGConfig(TypedDict):
    query: str
    message: str
    response: str
    is_correct:bool
    message_history: Annotated[list[str], operator.add]
    Personal_info: Annotated[list[str], operator.add]
    max_iterations: int
    error_message: str
    is_discriptive:bool
    route:str
    files:list[str]
    blocked: bool

from pydantic import BaseModel, Field
#for pydantic testing output


class ToolRoute(BaseModel):
    route: Literal["none", "docs", "iac"] = Field(
        description=(
            "'none' for general chat, greetings, or AWS trivia the model can "
            "answer without looking anything up. "
            "'docs' if the query needs AWS documentation/pricing lookup or an "
            "architecture recommendation grounded in current AWS docs. "
            "'iac' if the query needs CloudFormation/CDK code generation, "
            "validation, or deployment troubleshooting."
        )
    )
 
classifier_model = model.with_structured_output(ToolRoute)
def classify_route(query: str) -> str:
    try:
        result = classifier_model.invoke(f"Classify this query: {query}")
        return result.route
    except Exception:
        return "none"