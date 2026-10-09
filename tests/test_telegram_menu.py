from unittest.mock import Mock

import pytest
import requests

from tools.setup_telegram_menu import COMMANDS, KEYBOARD, TelegramMenu


class FakeMenu(TelegramMenu):
    def __init__(self, chat_type="private"):
        super().__init__("test-token", "123")
        self.chat_type = chat_type
        self.commands = [{"command": "custom", "description": "既有指令"}]
        self.calls = []

    def call(self, method, payload=None):
        self.calls.append((method, payload))
        if method == "getMe":
            return {"username": "test_bot"}
        if method == "getChat":
            return {"type": self.chat_type}
        if method == "getMyCommands":
            return self.commands
        if method == "setMyCommands":
            self.commands = payload["commands"]
            return True
        if method == "getChatMenuButton":
            return {"type": "commands"}
        if method == "sendMessage":
            return {"message_id": 42}
        return True


def test_check_is_read_only_and_does_not_start_polling():
    menu = FakeMenu()
    assert menu.check()["bot"] == "test_bot"
    assert [name for name, _ in menu.calls] == ["getMe", "getChat", "getMyCommands"]


def test_apply_sets_scoped_menu_preserves_custom_commands_and_sends_query_keyboard():
    menu = FakeMenu()
    result = menu.apply()
    assert result["keyboard_message_id"] == 42
    assert menu.commands == COMMANDS + [{"command": "custom", "description": "既有指令"}]
    updates = {name: payload for name, payload in menu.calls}
    assert updates["setMyCommands"]["scope"] == {"type": "chat", "chat_id": "123"}
    assert updates["setChatMenuButton"]["chat_id"] == "123"
    assert updates["sendMessage"]["chat_id"] == "123"
    keyboard = updates["sendMessage"]["reply_markup"]
    assert keyboard["is_persistent"] is True
    assert [[entry["text"] for entry in row] for row in keyboard["keyboard"]] == KEYBOARD
    assert "/go" not in sum(KEYBOARD, [])
    assert "getUpdates" not in updates


def test_group_keyboard_does_not_try_private_chat_menu_button():
    menu = FakeMenu("supergroup")
    menu.apply()
    assert "setChatMenuButton" not in [name for name, _ in menu.calls]
    assert menu.calls[-1][0] == "sendMessage"


def test_connection_error_does_not_expose_bot_token():
    menu = TelegramMenu("PRIVATE_TOKEN", "123")
    menu.session.post = Mock(side_effect=requests.exceptions.ProxyError("https://api.telegram.org/botPRIVATE_TOKEN/getMe"))
    with pytest.raises(RuntimeError) as error:
        menu.call("getMe")
    assert "PRIVATE_TOKEN" not in str(error.value)
    assert "ProxyError" in str(error.value)


def test_api_error_redacts_token_and_does_not_dump_response():
    menu = TelegramMenu("PRIVATE_TOKEN", "123")
    menu.session.post = Mock(return_value=Mock(ok=False, status_code=401,
                               json=lambda: {"ok": False, "description": "Bad PRIVATE_TOKEN"}))
    with pytest.raises(RuntimeError) as error:
        menu.call("getMe")
    assert "PRIVATE_TOKEN" not in str(error.value)


def test_repeat_apply_does_not_duplicate_existing_commands():
    menu = FakeMenu()
    menu.apply()
    menu.apply()
    assert len(menu.commands) == len(COMMANDS) + 1


def test_channel_fails_before_any_setting_or_message_is_written():
    menu = FakeMenu("channel")
    with pytest.raises(RuntimeError, match="頻道"):
        menu.apply()
    assert all(name.startswith("get") for name, _ in menu.calls)
