import dotenv
import os
dotenv.load_dotenv()
import operator
from nemoguardrails import LLMRails, RailsConfig
os.environ["OPENAI_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
rails_config = RailsConfig.from_path("C:\\aws_project\\rag_application\\config")
rails = LLMRails(rails_config)
from prompt_agent import run_prompt_agent
from langgraph.graph import StateGraph, START, END
from groq import BadRequestError
from state import RAGConfig,classify_route,TestRoute, model
from tools import load_mcp_tools
from promt import system_prompt,tester_prompt_code,tester_prompt_descriptive
import os
import uuid
import persistance_memo
import psycopg
from personal_memo import check_personal_info,TABLE_NAME_2


from chat_history import list_previous_sessions, DB_URL, TABLE_NAME, generate_title, save_session_title

conn = psycopg.connect(DB_URL,autocommit=True)
if not persistance_memo.init_postgres_history_table(conn, TABLE_NAME):
    raise SystemExit("Could not initialize chat history table — aborting.")
if not persistance_memo.init_postgres_history_table(conn, TABLE_NAME_2):
    raise SystemExit("Could not initialize personal memo table — aborting.")



tools = load_mcp_tools()




graph = StateGraph(RAGConfig)
docs_tools, iac_tools = load_mcp_tools()

model_docs = model.bind_tools(docs_tools)
model_iac = model.bind_tools(iac_tools)
 

def guard_input(state: RAGConfig):
    query = state["query"]
    result = rails.generate(messages=[{"role": "user", "content": query}])
    content = result.get("content", "") if isinstance(result, dict) else str(result)
    blocked = "sorry" in content.lower() or "can't respond" in content.lower() or "cannot respond" in content.lower()
    return {"response": content if blocked else "", "blocked": blocked}

def route_after_guard(state: RAGConfig):
    return END if state.get("blocked") else "Aws_agent"

def aws_agent(state: RAGConfig):
    previous_error = state.get("error_message", "")
    retry_note = ""
    if previous_error and previous_error.lower() != "none":
        retry_note = f'''

    IMPORTANT — Your previous attempt at this template failed validation.
    Error found: {previous_error}
    Fix this specific error in your new version. Do not repeat the same mistake.
    '''
    query = state["query"]
   
    message_history = state.get("message_history", "")
    formatted_history = "\n".join(message_history) if isinstance(message_history, list) else str(message_history)
    personal_info = state.get("Personal_info", "")
    formatted_personal = "\n".join(personal_info) if isinstance(personal_info, list) else str(personal_info)
 
    route = classify_route(query)
    state["route"] = route  # Store the route in the state for later use
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
            system_prompt.format(
                query=query,
                research_context=state.get("research_context", ""),
                message_history=formatted_history,
                personal_info=formatted_personal,
            ) + retry_note,
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
    return {"response": response.content,"route":route}

def testor_agent(state: RAGConfig):
    code = state["response"]
    route = state.get("route", "none")
    max_iterations = state.get("max_iterations", 0) + 1
    print(f"Testing the generated code. Attempt number: {state['max_iterations']}")

    if route == "iac":
        # Real validation: let the model actually call the tool and get a result back.
        raw_response = model_iac.invoke(
            tester_prompt_code.format(code=code, query=state["query"]),
            max_tokens=2000,
        )
        # If it made a tool call, execute it and feed the result back before asking for the verdict.
        if getattr(raw_response, "tool_calls", None):
            tool_msgs = []
            for call in raw_response.tool_calls:
                tool = next(t for t in iac_tools if t.name == call["name"])
                result = tool.invoke(call["args"])
                tool_msgs.append({"role": "tool", "tool_call_id": call["id"], "content": str(result)})
            verdict_model = model.with_structured_output(TestRoute)
            response = verdict_model.invoke(
                [raw_response] + tool_msgs + [
                    {"role": "user", "content": "Based on the tool result above, return the TestRoute verdict."}
                ]
            )
        else:
            verdict_model = model.with_structured_output(TestRoute)
            response = verdict_model.invoke(tester_prompt_code.format(code=code, query=state["query"]))
    else:
        # Descriptive answer: no tool involved, just a reasoning-based fact check.
        verdict_model = model.with_structured_output(TestRoute)
        response = verdict_model.invoke(
            tester_prompt_descriptive.format(answer=code, query=state["query"])
        )

    return {"is_correct": response.route, "error_message": response.error_message, "max_iterations": max_iterations}

def route_after_test(state: RAGConfig):
    if state["is_correct"] == "True" or state.get("max_iterations", 0) >= 5:
        return END
    return "Aws_agent"
graph.add_node("Guard_input", guard_input)
graph.add_node("Prompt_agent", run_prompt_agent)
graph.add_node("Aws_agent", aws_agent)
graph.add_node("Testor_agent", testor_agent)

graph.add_edge(START, "Guard_input")
graph.add_conditional_edges(
    "Guard_input",
    route_after_guard,
    {"Prompt_agent": "Prompt_agent", END: END}
)
graph.add_edge("Prompt_agent", "Aws_agent")
graph.add_edge("Aws_agent", "Testor_agent")
graph.add_conditional_edges(
    "Testor_agent",
    route_after_test,
    {"Aws_agent": "Aws_agent", END: END}
)


app=graph.compile()



##I am building a RAG application using Fast API, PostgreSQL with pgvector, and Claude API. I expect around 5,000 monthly active users
  # This should be unique per user/session in a real application
def generate_session_id():
    # Returns a unique, random 36-character string
    return str(uuid.uuid4())


# Example usage



def choose_session() -> str:
    """Lets the user resume a past session by title or start a fresh one."""
    choice = input("Resume a Previous chat or start a New one? (previous/new): ").strip().lower()

    if choice == "previous":
        sessions = list_previous_sessions(conn, TABLE_NAME)
        if not sessions:
            print("No previous sessions found. Starting a new one.")
            return str(uuid.uuid4())

        print("\n--- Previous Conversations ---")
        for i, (sid, title) in enumerate(sessions, start=1):
            clean_title = title if title else "Untitled Chat"
            print(f"  {i}. \"{clean_title}\"")

        pick = input("\nEnter the session number to resume: ").strip()
        try:
            index = int(pick) - 1
            if 0 <= index < len(sessions):
                selected_session_id = str(sessions[index][0])
                selected_title = sessions[index][1] or "Untitled Chat"
                
                print(f"\n================ Resuming Chat: \"{selected_title}\" ================")
                
                # Fetch last 5 messages preview
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
        if user_query.lower() == 'exit':
            break
        
            

        # Initialize state with the user's query
        

        # Fetch message history
        history_result = persistance_memo.get_postgres_history(conn, TABLE_NAME, session_id=session_id)
        if not history_result:
            title = generate_title(user_query)
            save_session_title(conn, session_id, title)

        all_personal_memos = persistance_memo.get_all_personal_memos(conn, TABLE_NAME_2)
        input_state = {
                "query": user_query,
                "message": "",
                "message_history": history_result,
                "Personal_info": all_personal_memos,
                "max_iterations": 0,
                "files": [],
            
            }
        
        result = app.invoke(input_state)
        print(result["response"])
        if check_personal_info(user_query).is_personal:
            persistance_memo.save_to_postgres_history(
                conn, TABLE_NAME_2, session_id=session_id, user_query=user_query, ai_response=result["response"]
            )
            print("[Saved to Personal Memory]")

        persistance_memo.save_to_postgres_history(conn, TABLE_NAME, session_id=session_id, user_query=user_query, ai_response=result["message"])


###1. Create file_parserfile, to read and save the data data loaded from the file
#2. provide the guardrails
#make it deployment redy
