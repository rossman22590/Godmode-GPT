"""File operations for AutoGPT"""
from __future__ import annotations

import os
import os.path
from pathlib import Path
from typing import Generator, List
import requests
from requests.adapters import HTTPAdapter
from requests.adapters import Retry
from colorama import Fore, Back
from autogpt.spinner import Spinner
from autogpt.utils import readable_file_size
from autogpt.workspace import path_in_workspace

def split_file(
    content: str, max_length: int = 4000, overlap: int = 0
) -> Generator[str, None, None]:
    """
    Split text into chunks of a specified maximum length with a specified overlap
    between chunks.

    :param content: The input text to be split into chunks
    :param max_length: The maximum length of each chunk,
        default is 4000 (about 1k token)
    :param overlap: The number of overlapping characters between chunks,
        default is no overlap
    :return: A generator yielding chunks of text
    """
    start = 0
    content_length = len(content)

    while start < content_length:
        end = start + max_length
        if end + overlap < content_length:
            chunk = content[start : end + overlap]
        else:
            chunk = content[start:content_length]
        yield chunk
        start += max_length - overlap


def download_file(url, filename):
    """Downloads a file
    Args:
        url (str): URL of the file to download
        filename (str): Filename to save the file as
    """
    safe_filename = path_in_workspace(filename)
    try:
        message = f"{Fore.YELLOW}Downloading file from {Back.LIGHTBLUE_EX}{url}{Back.RESET}{Fore.RESET}"
        with Spinner(message) as spinner:
            session = requests.Session()
            retry = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry)
            session.mount('http://', adapter)
            session.mount('https://', adapter)

            total_size = 0
            downloaded_size = 0

            with session.get(url, allow_redirects=True, stream=True) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('Content-Length', 0))
                downloaded_size = 0

                with open(safe_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded_size += len(chunk)

                         # Update the progress message
                        progress = f"{readable_file_size(downloaded_size)} / {readable_file_size(total_size)}"
                        spinner.update_message(f"{message} {progress}")

            return f'Successfully downloaded and locally stored file: "{filename}"! (Size: {readable_file_size(total_size)})'
    except requests.HTTPError as e:
        return f"Got an HTTP Error whilst trying to download file: {e}"
    except Exception as e:
        return "Error: " + str(e)


from google.cloud import firestore
from autogpt.api_utils import get_file, list_files, write_file

db = firestore.Client()
collection = db.collection("godmode-files")


def read_file(agent_id, filename):
    """Read a file and return the contents"""
    try:
        return get_file(filename, agent_id)
    except Exception as e:
        return "Error: " + str(e)


def write_to_file(agent_id, filename, text):
    """Write text to a file"""
    try:
        write_file(text, filename, agent_id)
        return "File written to successfully."
    except Exception as e:
        return "Error: " + str(e)


def append_to_file(agent_id, filename, text):
    """Append text to a file"""
    try:
        prevtxt = get_file(filename, agent_id)
        write_file(prevtxt + "\n" + text, filename, agent_id)

        return "Text appended successfully."
    except Exception as e:
        return "Error: " + str(e)


def delete_file(agent_id, filename):
    """Delete a file"""
    # no-op for simplicity
    return "File deleted successfully."


def search_files(agent_id):
    """Search for files in a directory"""
    try:
        return list_files(agent_id)
    except Exception as e:
        return "Error: " + str(e)
