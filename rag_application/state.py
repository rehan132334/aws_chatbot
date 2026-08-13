import operator
from typing import Annotated, TypedDict
import os
from dotenv import load_dotenv

load_dotenv()
import asyncio


#initiating the model
import os
from openai import OpenAI
from langchain_openai import ChatOpenAI

# 1. Initialize OpenAI client pointing to OpenRouter
model = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    model="google/gemma-4-26b-a4b-it:free",  # Or deepseek/deepseek-r1:free
    temperature=0,
    model_kwargs={
        "extra_body": {
            "reasoning": {
                "enabled": True  # Enables extended thinking / CoT
            }
        }
    }
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
class TestRoute(BaseModel):
    route: Literal["True", "False",] = Field(
        description=(
            "'True' if the code is correct. "
            "'False' if the code has errors."
        )
    )
    error_message: str = Field(
        description=(
            "If the code has errors, provide a brief error message or description. "
            "If the code is correct, this field can be empty or 'None'."
        )
    )

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