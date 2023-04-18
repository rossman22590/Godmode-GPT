from functools import wraps
import json
import logging
import time
import traceback
from autogpt.config.ai_config import AIConfig
from autogpt.memory import get_memory
import autogpt.chat as chat
from autogpt.config import Config
import os
from openai.error import OpenAIError
import firebase_admin
from firebase_admin import auth as firebase_auth
from autogpt.llm_utils import create_chat_completion
from autogpt.api_utils import get_file_urls
import logging
from autogpt.agent.agent import Agent

from autogpt.config import Config
from autogpt.logs import logger
from autogpt.memory import get_memory
from autogpt.memory.pinecone import PineconeMemory
from google.cloud import datastore

client = datastore.Client()

global_config = Config()

START = "###start###"

def new_interact(
    cfg: Config,
    ai_config: AIConfig,
    memory: PineconeMemory,
    command_name: str,
    arguments: str,
    assistant_reply: str,
    agent_id: str,
    full_message_history=[],
):
    task = datastore.Entity(key=client.key("Task"))
    key = client.key("Agent", agent_id)

    logger.set_level(logging.DEBUG if cfg.debug_mode else logging.INFO)
    system_prompt = ai_config.construct_full_prompt()
    # print(prompt)
    # Initialize variables
    full_message_history = []
    next_action_count = 0
    # Make a constant:
    triggering_prompt = (
        "Determine which next command to use, and respond using the"
        " format specified above:"
    )
    # Initialize memory and make sure it is empty.
    # this is particularly important for indexing and referencing pinecone memory
    agent = Agent(
        ai_name=ai_config.ai_name, # save
        ai_role=ai_config.ai_role, # save 
        ai_goals=ai_config.ai_goals, # save
        agent_id=agent_id, # save
        full_message_history=full_message_history, # save
        command_name=command_name, # save
        arguments=arguments, # save
        assistant_reply=assistant_reply, # save
        agents={}, # save
        triggering_prompt=triggering_prompt,
        system_prompt=system_prompt,
        memory=memory,
        next_action_count=next_action_count,
        cfg=cfg,
    )

    (
        command_name,
        arguments,
        thoughts,
        full_message_history,
        assistant_reply,
        result,
    ) = agent.single_step(
        command_name=command_name,
        arguments=arguments,
    )
    entity = datastore.Entity(key=key)
    entity.update({
        "ai_name": agent.ai_name,
        "ai_role": agent.ai_role,
        "ai_goals": agent.ai_goals,
        "agent_id": agent.agent_id,
        "full_message_history": agent.full_message_history,
        "command_name": agent.command_name,
        "arguments": agent.arguments,
        "assistant_reply": agent.assistant_reply,
        "agents": agent.agent_manager.agents,
    }, exclude_from_indexes=['full_message_history', 'agents', 'assistant_reply', 'arguments', 'command_name'])
    client.put(entity)

    # generate simplified task name
    task = None
    try:
        task = create_chat_completion(
            [
                chat.create_chat_message(
                    "system",
                    "You are ChatGPT, a large language model trained by OpenAI.\nKnowledge cutoff: 2021-09\nCurrent date: 2023-03-26",
                ),
                chat.create_chat_message(
                    "user",
                    'Describe this action as succinctly as possible in one short sentence:\n\n```\nCOMMAND: browse_website\nARGS: {\n  "url": "https://www.amazon.com/",\n  "question": "What are the current top products in the Smart Home Device category?"\n}\n```',
                ),
                chat.create_chat_message(
                    "assistant", "Find top Smart Home Device products on Amazon.com."
                ),
                chat.create_chat_message(
                    "user",
                    f"Describe this action as succinctly as possible in one short sentence:\n\n```\nCOMMAND: {command_name}\nARGS: {arguments}\n```",
                ),
            ],
            model="gpt-3.5-turbo",
            temperature=0.2,
            cfg=cfg,
        )
    except Exception as e:
        print(e)

    return (
        command_name,
        arguments,
        thoughts,
        full_message_history,
        assistant_reply,
        result,
        task,
    )


# make an api using flask

from flask import Flask, jsonify, request


class LogRequestDurationMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        request_start_time = time.time()
        response = self.app(environ, start_response)
        request_duration = time.time() - request_start_time
        app.logger.info(f"Request duration: {request_duration}")
        return response


from flask_limiter import Limiter

app = Flask(__name__)

def get_remote_address() -> str:
    return (
        request.environ.get("HTTP_X_FORWARDED_FOR")
        or request.environ.get("REMOTE_ADDR")
        or request.remote_addr
    ) # type: ignore


if global_config.redis_host is None:
    print("No redis host, using local limiter")
    limiter = Limiter(app=app, key_func=get_remote_address)
else:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        storage_uri=f"redis://{global_config.redis_host}:{global_config.redis_port}",
    )

app.wsgi_app = LogRequestDurationMiddleware(app.wsgi_app)


@app.after_request
def after_request(response):
    ip = get_remote_address()
    openai_key = "None"
    try:
        if request.json is not None:
            openai_key = request.json["openai_key"]
            openai_key = openai_key[:5] + "..." + openai_key[-5:]
    except Exception as e:
        pass
    # check if request has user
    if hasattr(request, "user"):
        print(
            f"{request.method} {request.path} {response.status_code}: IP {ip} from user {request.user} with key {openai_key}"
        )
    else:
        print(
            f"{request.method} {request.path} {response.status_code}: IP {ip} with no user with key {openai_key}"
        )
    white_origin = ["http://localhost:3000"]
    # if request.headers['Origin'] in white_origin:
    if True:
        response.headers["Access-Control-Allow-Origin"] = request.headers.get(
            "Origin", ""
        )
        response.headers["Access-Control-Allow-Methods"] = "PUT,GET,POST,DELETE"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response


@app.route("/health", methods=["GET"])
def health():
    return "OK"


def make_rate_limit(rate: str):
    def get_rate_limit():
        request_data = request.get_json()
        if (
            request_data.get("openai_key", None) is not None
            and len(request_data.get("openai_key", "")) > 0
        ):
            return "1000 per day;600 per hour;100 per minute"

        return rate

    return get_rate_limit


firebase_admin.initialize_app()


def verify_firebase_token(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            request_data = request.get_json()
            if (
                request_data.get("openai_key", None) is not None
                and len(request_data.get("openai_key", "")) > 0
            ):
                return f(*args, **kwargs)
        except Exception as e:
            print(e)

        id_token = request.headers.get("Authorization")
        if not id_token:
            return (
                jsonify(
                    {
                        "error": "Unauthorized",
                        "message": "Please login or set an API key to continue",
                    }
                ),
                401,
            )

        try:
            # Remove 'Bearer ' from the token if it's present
            if id_token.startswith("Bearer "):
                id_token = id_token[7:]
            decoded_token = firebase_auth.verify_id_token(id_token)
            request.user = decoded_token
        except ValueError as e:
            return jsonify({"error": "Unauthorized", "message": str(e)}), 401
        except Exception as e:
            return jsonify({"error": "Unauthorized", "message": str(e)}), 401

        return f(*args, **kwargs)

    return wrapper


@app.route("/api-goal-subgoals", methods=["POST"]) # type: ignore
@limiter.limit(make_rate_limit("100 per day;60 per hour;15 per minute"))
@verify_firebase_token
def subgoals():
    request_data = request.get_json()

    goal = request_data["goal"]
    cfg = Config()
    cfg.openai_api_key = request_data.get("openai_key", None)

    subgoals = []
    try:
        subgoals = create_chat_completion(
            [
                chat.create_chat_message(
                    "system",
                    "You are ChatGPT, a large language model trained by OpenAI.\nKnowledge cutoff: 2021-09\nCurrent date: 2023-03-26",
                ),
                chat.create_chat_message(
                    "user",
                    f'Make a list of 3 subtasks to the overall goal of: "{goal}".\n'
                    + "\n"
                    + "ONLY answer this message with a numbered list of short, standalone subtasks. write nothing else. Make sure to make the subtask descriptions as brief as possible.",
                ),
            ],
            model="gpt-3.5-turbo",
            temperature=0.2,
            max_tokens=150,
            cfg=cfg,
        )
    except Exception as e:
        if isinstance(e, OpenAIError):
            return e.error, 503

    return json.dumps(
        {
            "subgoals": subgoals,
        }
    )


@app.route("/api/v2", methods=["POST"]) # type: ignore
@limiter.limit(make_rate_limit("500 per day;200 per hour;8 per minute"))
@verify_firebase_token
def godmode_main():
    try:
        request_data = request.get_json()

        command_name = request_data["command"]
        arguments = request_data["arguments"]
        assistant_reply = request_data.get("assistant_reply", "")

        ai_name = request_data["ai_name"]
        ai_description = request_data["ai_description"]
        ai_goals = request_data["ai_goals"]
        message_history = request_data.get("message_history", [])

        agent_id = request_data["agent_id"]

        openai_key = request_data.get("openai_key", None)
        gpt_model = "gpt-3.5-turbo"
        if len(openai_key or "") > 0:
            gpt_model = request_data.get("gpt_model", "gpt-3.5-turbo")
        else:
            gpt_model = "gpt-3.5-turbo"

        cfg = Config()
        cfg.openai_api_key = openai_key
        cfg.smart_llm_model = gpt_model
        cfg.agent_id = agent_id

        memory: PineconeMemory = get_memory(cfg) # type: ignore

        ai_config = AIConfig(
            ai_name=ai_name,
            ai_role=ai_description,
            ai_goals=ai_goals,
        )

        (
            command_name,
            arguments,
            thoughts,
            message_history,
            assistant_reply,
            result,
            task,
        ) = new_interact(
            cfg=cfg,
            ai_config=ai_config,
            memory=memory,
            command_name=command_name,
            arguments=arguments,
            assistant_reply=assistant_reply,
            agent_id=agent_id,
            full_message_history=message_history,
        )
    except Exception as e:
        if isinstance(e, OpenAIError):
            return e.error, 503

        # dump stacktrace to console
        print("simple_api error", e)
        traceback.print_exc()
        raise e

    return json.dumps(
        {
            "command": command_name,
            "arguments": arguments,
            "thoughts": thoughts,
            "message_history": message_history,
            "assistant_reply": assistant_reply,
            "result": result,
            "task": task,
        }
    )


@app.route("/api/files", methods=["POST"]) # type: ignore
@limiter.limit("800 per day;400 per hour;16 per minute")
# @verify_firebase_token
def api_files():
    try:
        request_data = request.get_json()
        agent_id = request_data["agent_id"]
        
        files = get_file_urls(agent_id)
        return files
    except Exception as e:
        if isinstance(e, OpenAIError):
            return e.error, 503

        # dump stacktrace to console
        print("api_files error", e)
        traceback.print_exc()
        raise e


port = os.environ.get("PORT") or 5100
host = os.environ.get("HOST") or None

if __name__ == "__main__":
    print("Starting API on port", port, "and host", host)
    app.run(debug=True, port=port, host=host)
