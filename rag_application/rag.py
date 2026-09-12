import dotenv
import os
import json
import uuid

from nemoguardrails import LLMRails, RailsConfig
from langgraph.graph import StateGraph, START, END
from groq import BadRequestError
import psycopg

from prompt_agent import run_prompt_agent
from state import RAGConfig, classify_route, model
from tools import load_mcp_tools
from promt import system_prompt, SAFETY_PROMPT, AWS_TOPIC_PROMPT, OUTPUT_SAFETY_PROMPT
import persistance_memo
from personal_memo import check_personal_info, TABLE_NAME_2
from chat_history import list_previous_sessions, DB_URL, TABLE_NAME

dotenv.load_dotenv()

print("loading rails config...", flush=True)
rails_config = RailsConfig.from_path("/app/rag_application/config")
print("rails config loaded, building LLMRails...", flush=True)
rails = LLMRails(rails_config)

conn = psycopg.connect(DB_URL, autocommit=True)
if not persistance_memo.init_postgres_history_table(conn, TABLE_NAME):
    raise SystemExit("Could not initialize chat history table — aborting.")
if not persistance_memo.init_postgres_history_table(conn, TABLE_NAME_2):
    raise SystemExit("Could not initialize personal memo table — aborting.")

tools = load_mcp_tools()
docs_tools, iac_tools = load_mcp_tools()

model_docs = model.bind_tools(docs_tools)
model_iac = model.bind_tools(iac_tools)

graph = StateGraph(RAGConfig)








def _invoke_classifier(prompt):
    result = model.invoke(prompt, max_tokens=200)
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content).strip()


def _parse_json_object(content):
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def is_safe_input(query):
    content = _invoke_classifier(SAFETY_PROMPT.replace("{query}", query))
    data = _parse_json_object(content)
    return data.get("safe") is True


def is_aws_topic(query):
    content = _invoke_classifier(AWS_TOPIC_PROMPT.replace("{query}", query))
    data = _parse_json_object(content)
    return data.get("topic") == "AWS"


def is_safe_output(query, response):
    content = _invoke_classifier(
        OUTPUT_SAFETY_PROMPT.replace("{query}", query).replace("{response}", response)
    )
    data = _parse_json_object(content)
    return data.get("safe") is True


def guard_input(state: RAGConfig):
    query = state["query"].strip()

    if not query:
        return {
            "response": "I can't answer an empty question.",
            "blocked": True,
        }

    try:
        if not is_safe_input(query):
            print("[Input Safety]: BLOCKED")
            return {
                "response": "I can't answer that request.",
                "blocked": True,
            }
    except Exception as e:
        print(f"[Input Safety Error]: {e}")
        return {
            "response": "I can't process this request.",
            "blocked": True,
        }

    try:
        if not is_aws_topic(query):
            print("[AWS Scope]: OFF_TOPIC")
            return {
                "response": "The topic is not related to AWS, so I can't answer.",
                "blocked": True,
            }
    except Exception as e:
        print(f"[AWS Scope Error]: {e}")
        return {
            "response": "I can't process this request.",
            "blocked": True,
        }

    print("[Input Gate]: SAFE + AWS")
    return {
        "response": "",
        "blocked": False,
    }


def route_after_guard(state: RAGConfig):
    return END if state.get("blocked") else "Prompt_agent"


def aws_agent(state: RAGConfig):
    previous_error = state.get("error_message", "")
    retry_note = ""
    if previous_error and previous_error.lower() != "none":
        retry_note = f"""

IMPORTANT — Your previous attempt at this template failed validation.
Error found: {previous_error}
Fix this specific error in your new version. Do not repeat the same mistake.
"""

    query = state["query"]
    message_history = state.get("message_history", "")
    formatted_history = "\n".join(message_history) if isinstance(message_history, list) else str(message_history)
    personal_info = state.get("Personal_info", "")
    formatted_personal = "\n".join(personal_info) if isinstance(personal_info, list) else str(personal_info)

    route = classify_route(query)
    state["route"] = route

    if route == "docs":
        active_model = model_docs
        print("Using 'docs' model for AWS documentation lookup or architecture recommendation.")
    elif route == "iac":
        active_model = model_iac
        print("Using 'iac' model for Infrastructure as Code related queries.")
    else:
        active_model = model
        print("Using default model for general queries.")

    try:
        response = active_model.invoke(
            system_prompt.replace("{query}", query).replace("{research_context}", state.get("research_context", "")).replace("{message_history}", formatted_history).replace("{personal_info}", formatted_personal)
            + retry_note,
            max_tokens=2000,
        )
    except BadRequestError as e:
        if "tool_use_failed" in str(e):
            response = model.invoke(
                system_prompt.format(
                    query=query,
                    research_context=state.get("research_context", ""),
                    message_history=formatted_history,
                    personal_info=formatted_personal,
                ) + retry_note,
                max_tokens=2000,
            )
        else:
            raise

    return {
        "response": response.content,
        "route": route,
    }


def guard_output(state: RAGConfig):
    query = state.get("query", "")
    response = state.get("response", "")

    if not response:
        return {
            "response": "I couldn't generate a response.",
            "blocked": True,
        }

    try:
        if not is_safe_output(query, response):
            print("[Output Safety]: BLOCKED")
            return {
                "response": "I can't provide that response.",
                "blocked": True,
            }
    except Exception as e:
        print(f"[Output Safety Error]: {e}")
        return {
            "response": "I can't provide a response to this request.",
            "blocked": True,
        }

    print("[Output Safety]: SAFE")
    return {
        "response": response,
        "blocked": False,
    }


graph.add_node("Guard_input", guard_input)
graph.add_node("Prompt_agent", run_prompt_agent)
graph.add_node("Aws_agent", aws_agent)
graph.add_node("Guard_output", guard_output)

graph.add_edge(START, "Guard_input")
graph.add_conditional_edges(
    "Guard_input",
    route_after_guard,
    {
        "Prompt_agent": "Prompt_agent",
        END: END,
    },
)
graph.add_edge("Prompt_agent", "Aws_agent")
graph.add_edge("Aws_agent", "Guard_output")
graph.add_edge("Guard_output", END)

app = graph.compile()


def generate_session_id():
    return str(uuid.uuid4())


def choose_session() -> str:
    choice = input("Resume a Previous chat or start a New one? (previous/new): ").strip().lower()

    if choice == "previous":
        sessions = list_previous_sessions(conn, TABLE_NAME)
        if not sessions:
            print("No previous sessions found. Starting a new one.")
            return str(uuid.uuid4())

        print("\n--- Previous Conversations ---")
        for i, (sid, title) in enumerate(sessions, start=1):
            clean_title = title if title else "Untitled Chat"
            print(f'  {i}. "{clean_title}"')

        pick = input("\nEnter the session number to resume: ").strip()
        try:
            index = int(pick) - 1
            if 0 <= index < len(sessions):
                selected_session_id = str(sessions[index][0])
                selected_title = sessions[index][1] or "Untitled Chat"

                print(f'\n================ Resuming Chat: "{selected_title}" ================')

                recent_msgs = persistance_memo.get_recent_messages_preview(
                    conn, TABLE_NAME, selected_session_id, limit=5
                )
                if recent_msgs:
                    print("\n--- Last 5 Messages in Context ---")
                    for role, content in recent_msgs:
                        print(f"[{role}]: {content}")
                    print("----------------------------------\n")
                else:
                    print("No prior history found for this session.\n")

                return selected_session_id
        except (ValueError, IndexError):
            pass

        print("Invalid selection. Starting a new session instead.")
        return str(uuid.uuid4())

    return str(uuid.uuid4())


if __name__ == "__main__":
    session_id = choose_session()
    while True:
        user_query = input("Enter your project query (or type 'exit' to quit): ")
        if user_query.lower() == "exit":
            break

        input_state = RAGConfig(
            query=user_query,
            message="",
            response="",
            is_correct=False,
            message_history=[],
            Personal_info=[],
            max_iterations=0,
            error_message="None",
            is_descriptive=False,
            route="none",
            files=[],
            blocked=False,
        )

        result = app.invoke(input_state)
        print(result["response"])

        if not result.get("blocked"):
            if check_personal_info(user_query).is_personal:
                persistance_memo.save_to_postgres_history(
                    conn,
                    TABLE_NAME_2,
                    session_id=session_id,
                    user_query=user_query,
                    ai_response=result["response"],
                )
                print("[Saved to Personal Memory]")

            persistance_memo.save_to_postgres_history(
                conn,
                TABLE_NAME,
                session_id=session_id,
                user_query=user_query,
                ai_response=result.get("response", ""),
            )
