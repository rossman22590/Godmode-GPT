"""Unit tests for the commands module"""
from unittest.mock import MagicMock, patch

import pytest

from autogpt.agent_manager import list_agents, start_agent
from autogpt.app import execute_command


@pytest.mark.integration_test
def test_make_agent() -> None:
    """Test the make_agent command"""
    with patch("openai.ChatCompletion.create") as mock:
        obj = MagicMock()
        obj.response.choices[0].messages[0].content = "Test message"
        mock.return_value = obj
        start_agent("Test Agent", "chat", "Hello, how are you?", "gpt2")
        agents = list_agents()
        assert "List of agents:\n0: chat" == agents
        start_agent("Test Agent 2", "write", "Hello, how are you?", "gpt2")
        agents = list_agents()
        assert "List of agents:\n0: chat\n1: write" == agents
