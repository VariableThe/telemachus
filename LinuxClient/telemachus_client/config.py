"""INI file + CLI configuration for the Linux client (stdlib only).

File layout (``~/.config/telemachus/client.conf``)::

    [client]
    host = 192.168.1.10
    port = 54321
    token = BASE64URL_32_BYTE_TOKEN
    name = my-linux-box
    decoder = auto
    display = :0
    fullscreen = true
    input_enabled = true

Precedence is CLI > file > defaults. CLI parsers must use ``default=None``
for every overridable option so "unset" is distinguishable from an explicit
value (in particular, boolean flags must default to ``None``, not
``False``, or they would silently override the file).
"""

from __future__ import annotations

import base64
import binascii
import configparser
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from .protocol import DEFAULT_PORT

CONFIG_PATH = Path.home() / ".config" / "telemachus" / "client.conf"

_TOKEN_B64URL_RE = re.compile(r"^[A-Za-z0-9\-_]+$")


@dataclass
class ClientConfig:
    host: str
    port: int
    token: bytes
    name: str
    decoder: str = "auto"
    display: Optional[str] = None
    fullscreen: bool = True
    input_enabled: bool = True


def format_token(b64url: str) -> bytes:
    """Decode a base64url (no padding) token string to its 32 raw bytes."""
    if isinstance(b64url, bytes):
        try:
            text = b64url.decode("ascii")
        except UnicodeDecodeError:
            raise ValueError("token is not ASCII base64url") from None
    else:
        text = b64url.strip()
    if not _TOKEN_B64URL_RE.match(text):
        raise ValueError("token is not base64url")
    raw = text.encode("ascii") + b"=" * (-len(text) % 4)
    try:
        token = base64.b64decode(raw, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"malformed token: {exc}") from None
    if len(token) != 32:
        raise ValueError(f"token must decode to 32 bytes, got {len(token)}")
    return token


_TRUE_WORDS = {"1", "true", "yes", "on"}
_FALSE_WORDS = {"0", "false", "no", "off"}


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    word = str(value).strip().lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    raise ValueError(f"not a boolean: {value!r}")


def _truncate_name_64(name: str) -> str:
    raw = name.encode("utf-8")
    if len(raw) <= 64:
        return name
    cut = raw[:64]
    while True:
        try:
            return cut.decode("utf-8")
        except UnicodeDecodeError:
            cut = cut[:-1]


def load_config(path: Union[Path, str, None] = None) -> Dict[str, Any]:
    """Read the INI file; return coerced settings, or ``{}`` if absent.

    Only the ``[client]`` section is read (a section-less file is treated as
    if its keys were under ``[client]``). ``port`` is coerced to int and
    ``fullscreen``/``input_enabled`` to bool; ``token`` is kept as the raw
    base64url string and decoded later by :func:`build_config`.
    """
    cfg_path = Path(path) if path is not None else CONFIG_PATH
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ValueError(f"cannot read config {cfg_path}: {exc}") from None
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.MissingSectionHeader:
        parser = configparser.ConfigParser()
        parser.read_string("[client]\n" + text)
    if not parser.has_section("client"):
        return {}
    section = parser["client"]
    out: Dict[str, Any] = {}
    for key in (
        "host",
        "port",
        "token",
        "name",
        "decoder",
        "display",
        "fullscreen",
        "input_enabled",
    ):
        if key not in section:
            continue
        raw_value = section[key]
        try:
            if key == "port":
                out[key] = int(raw_value)
            elif key in ("fullscreen", "input_enabled"):
                out[key] = _parse_bool(raw_value)
            else:
                out[key] = raw_value
        except ValueError as exc:
            raise ValueError(
                f"invalid config value for {key!r} in {cfg_path}: {exc}"
            ) from None
    return out


def _cli_get(cli_args: Any, key: str) -> Any:
    if cli_args is None:
        return None
    if isinstance(cli_args, Mapping):
        return cli_args.get(key)
    return getattr(cli_args, key, None)


def _pick(cli_args: Any, file_cfg: Mapping[str, Any], key: str, default: Any) -> Any:
    cli_value = _cli_get(cli_args, key)
    if cli_value is not None:
        return cli_value
    if key in file_cfg:
        return file_cfg[key]
    return default


def build_config(cli_args: Any, file_cfg: Mapping[str, Any]) -> ClientConfig:
    """Merge CLI args over file settings over defaults into a ClientConfig.

    ``cli_args`` may be an ``argparse.Namespace``, a plain dict, or ``None``;
    ``None`` values mean "unset". ``token`` accepts a base64url string or
    raw 32 bytes; when absent it defaults to ``b""`` (USB/loopback mode,
    where :meth:`StreamClient.connect` skips the handshake). ``name``
    defaults to the local hostname truncated to 64 UTF-8 bytes.
    """
    host = str(_pick(cli_args, file_cfg, "host", "127.0.0.1"))
    try:
        port = int(_pick(cli_args, file_cfg, "port", DEFAULT_PORT))  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid port: {exc}") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be 1..65535, got {port}")

    token_raw = _pick(cli_args, file_cfg, "token", None)
    if token_raw is None or token_raw == "":
        token = b""
    elif isinstance(token_raw, bytes):
        if len(token_raw) != 32:
            raise ValueError(f"token must be 32 bytes, got {len(token_raw)}")
        token = bytes(token_raw)
    elif isinstance(token_raw, str):
        token = format_token(token_raw)
    else:
        raise ValueError(f"token must be base64url str or 32 bytes, got {type(token_raw)}")

    name_raw = _pick(cli_args, file_cfg, "name", None)
    if name_raw is None or str(name_raw) == "":
        try:
            name_raw = socket.gethostname()
        except OSError:
            name_raw = "linux"
    name = _truncate_name_64(str(name_raw))
    if not name.encode("utf-8"):
        name = "linux"

    fullscreen_raw = _pick(cli_args, file_cfg, "fullscreen", True)
    input_raw = _pick(cli_args, file_cfg, "input_enabled", True)
    try:
        fullscreen = _parse_bool(fullscreen_raw)
        input_enabled = _parse_bool(input_raw)
    except ValueError as exc:
        raise ValueError(f"invalid boolean config: {exc}") from None

    display_raw = _pick(cli_args, file_cfg, "display", None)
    return ClientConfig(
        host=host,
        port=port,
        token=token,
        name=name,
        decoder=str(_pick(cli_args, file_cfg, "decoder", "auto")),
        display=None if display_raw is None else str(display_raw),
        fullscreen=fullscreen,
        input_enabled=input_enabled,
    )
