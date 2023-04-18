from __future__ import annotations
import time
from typing import List, Dict, Optional

import openai
from openai.error import APIError, RateLimitError
from colorama import Fore

def call_ai_function(
    function: str, args: List[str], description: str, cfg: object, model: str | None = None
) -> str:
    """Call an AI function

    This is a magic function that can do anything with no-code. See
    https://github.com/Torantulino/AI-Functions for more info.

    Args:
        function (str): The function to call
        args (list): The arguments to pass to the function
        description (str): The description of the function
        model (str, optional): The model to use. Defaults to None.

    Returns:
        str: The response from the function
    """
    if model is None:
        model = cfg.smart_llm_model
    # For each arg, if any are None, convert to "None":
    args = [str(arg) if arg is not None else "None" for arg in args]
    # parse args to comma separated string
    sargs = ", ".join(args)
    messages = [
        {
            "role": "system",
            "content": f"You are now the following python function: ```# {description}"
            f"\n{function}```\n\nOnly respond with your `return` value.",
        },
        {"role": "user", "content": sargs},
    ]

    return create_chat_completion(model=model, messages=messages, temperature=0, cfg=cfg)


# Overly simple abstraction until we create something better
# simple retry mechanism when getting a rate error or a bad gateway
def create_chat_completion(
    messages: List[Dict[str, str]],
    cfg,
    model: str | None = "gpt-3.5-turbo",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Create a chat completion using the OpenAI API

    Args:
        messages (list[dict[str, str]]): The messages to send to the chat completion
        model (str, optional): The model to use. Defaults to None.
        temperature (float, optional): The temperature to use. Defaults to 0.9.
        max_tokens (int, optional): The max tokens to use. Defaults to None.

    Returns:
        str: The response from the chat completion
    """
    if model is None:
        model = "gpt-3.5-turbo"
    t0 = time.time()
    if temperature is None:
        temperature = cfg.temperature
    response = None
    num_retries = 1
    if cfg.debug_mode:
        print(
            Fore.GREEN
            + f"Creating chat completion with model {model}, temperature {temperature},"
            f" max_tokens {max_tokens}" + Fore.RESET
        )
    for attempt in range(num_retries):
        backoff = 2 ** (attempt + 2)
        try:
            if cfg.use_azure:
                response = openai.ChatCompletion.create(
                    deployment_id=cfg.get_azure_deployment_id_for_model(model), # type: ignore
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            else:
                response = openai.ChatCompletion.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_key=cfg.openai_api_key,
                )
            break
        except RateLimitError:
            if cfg.debug_mode:
                print(
                    Fore.RED + "Error: ",
                    f"Reached rate limit, passing..." + Fore.RESET,
                )
        except APIError as e:
            if e.http_status == 502:
                pass
            else:
                raise
            if attempt == num_retries - 1:
                raise
        if cfg.debug_mode:
            print(
                Fore.RED + "Error: ",
                f"API Bad gateway. Waiting {backoff} seconds..." + Fore.RESET,
            )
        # time.sleep(backoff)
    if response is None:
        raise RuntimeError(f"Failed to get response after {num_retries} retries")
    
    print(f"CHAT COMPLETION TOOK {time.time() - t0} SECONDS", model)

    return response.choices[0].message["content"] # type: ignore


def create_embedding_with_ada(text: str, cfg: Config) -> Optional[List]:
    """Create a embedding with text-ada-002 using the OpenAI SDK"""
    num_retries = 10
    for attempt in range(num_retries):
        backoff = 2 ** (attempt + 2)
        try:
            if cfg.use_azure:
                return openai.Embedding.create(
                    input=[text], # type: ignore
                    engine=cfg.get_azure_deployment_id_for_model(
                        "text-embedding-ada-002"
                    ),
                )["data"][0]["embedding"]
            else:
                return openai.Embedding.create(
                    input=[text], # type: ignore
                    model="text-embedding-ada-002",
                    api_key=cfg.openai_api_key,
                )["data"][0]["embedding"]
        except RateLimitError:
            pass
        except APIError as e:
            if e.http_status == 502:
                pass
            else:
                raise
            if attempt == num_retries - 1:
                raise
        if cfg.debug_mode:
            print(
                Fore.RED + "Error: ",
                f"API Bad gateway. Waiting {backoff} seconds..." + Fore.RESET,
            )
        # time.sleep(backoff)
