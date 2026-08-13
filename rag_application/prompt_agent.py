from state import RAGConfig, model
from promt import PROMPT_AGENT_SYSTEM_INSTRUCTIONS
from langchain_core.messages import SystemMessage, HumanMessage

def run_prompt_agent(state: RAGConfig) -> dict:
    # 1. Safely extract attributes whether state is a Pydantic model or dict
    files = getattr(state, "files", state.get("files") if isinstance(state, dict) else None)
    query = getattr(state, "query", state.get("query") if isinstance(state, dict) else "")

    # 2. Build file context safely across list vs dict input formats
    file_context = ""

    if isinstance(files, list):
        for file_obj in files:
            if isinstance(file_obj, dict):
                name = file_obj.get("name", "unknown_file")
                content = file_obj.get("content", "")
                file_context += f"\n<file name='{name}'>\n{content}\n</file>\n"
            elif isinstance(file_obj, str):
                file_context += f"\n<file>\n{file_obj}\n</file>\n"

    elif isinstance(files, dict):
        for name, content in files.items():
            file_context += f"\n<file name='{name}'>\n{content}\n</file>\n"

    # 3. Construct user message payload
    user_payload = f"""
    <attached_files>
    {file_context if file_context else "No files provided."}
    </attached_files>

    Raw User Query:
    "{query}"
    """

    # 4. Pass System Instructions & User Payload as separate messages
    # (Avoids calling .format() on system instructions containing JSON curly braces)
    messages = [
        SystemMessage(content=PROMPT_AGENT_SYSTEM_INSTRUCTIONS),
        HumanMessage(content=user_payload)
    ]

    response = model.invoke(messages, max_tokens=2000)

    # 5. Return dict matching LangGraph state key updates
    return {"query": response.content}