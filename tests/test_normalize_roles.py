from core.inference import _normalize_roles


def test_consecutive_user_merged():
    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "user", "content": "Hola"},
        {"role": "user", "content": "Quiero un completo"},
        {"role": "assistant", "content": "Anotado"},
    ]
    result = _normalize_roles(messages)
    assert len(result) == 3
    assert result[0]["role"] == "system"
    assert result[1]["role"] == "user"
    assert "Hola" in result[1]["content"]
    assert "Quiero un completo" in result[1]["content"]
    assert result[2]["role"] == "assistant"


def test_consecutive_assistant_merged():
    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "assistant", "content": "Hola"},
        {"role": "assistant", "content": "Algo mas"},
    ]
    result = _normalize_roles(messages)
    assert len(result) == 2
    assert result[1]["role"] == "assistant"
    assert "Hola" in result[1]["content"]
    assert "Algo mas" in result[1]["content"]


def test_consecutive_system_merged():
    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "system", "content": "extra context"},
        {"role": "user", "content": "Hola"},
    ]
    result = _normalize_roles(messages)
    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert "prompt" in result[0]["content"]
    assert "extra context" in result[0]["content"]


def test_alternating_unchanged():
    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Bienvenido"},
        {"role": "user", "content": "Pedido"},
    ]
    result = _normalize_roles(messages)
    assert len(result) == 4
    assert [m["role"] for m in result] == ["system", "user", "assistant", "user"]


def test_empty_input():
    result = _normalize_roles([])
    assert result == []
