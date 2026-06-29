"""The interactive address picker (``cli._choose_ip``).

Drives it with scripted ``input()`` responses; ``capsys`` swallows the prompts.
"""

from phonesense import cli

IPS = ["192.168.1.42", "10.0.0.5", "172.20.0.3"]


def _scripted_input(monkeypatch, *responses):
    it = iter(responses)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def test_enter_takes_the_default(monkeypatch, capsys):
    _scripted_input(monkeypatch, "")
    assert cli._choose_ip(IPS) == "192.168.1.42"


def test_number_selects_that_address(monkeypatch, capsys):
    _scripted_input(monkeypatch, "2")
    assert cli._choose_ip(IPS) == "10.0.0.5"


def test_reprompts_until_valid(monkeypatch, capsys):
    _scripted_input(monkeypatch, "9", "abc", "3")
    assert cli._choose_ip(IPS) == "172.20.0.3"
    assert "Enter a number from the list." in capsys.readouterr().out


def test_eof_falls_back_to_default(monkeypatch, capsys):
    def _raise(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    assert cli._choose_ip(IPS) == "192.168.1.42"
