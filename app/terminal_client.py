import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from urllib.parse import quote

import websockets
from websockets.exceptions import ConnectionClosed, InvalidURI


DEFAULT_BASE_URL = "ws://localhost:8000"
DEFAULT_CHANNEL_ID = "canal-geral"
RECONNECT_DELAY_SECONDS = 2.0


def build_websocket_url(base_url: str, channel_id: str, usuario: str) -> str:
    clean_base_url = base_url.rstrip("/")
    return (
        f"{clean_base_url}/ws/channel/{quote(channel_id, safe='')}"
        f"?usuario={quote(usuario, safe='')}"
    )


def create_message(usuario: str, corpo_texto: str) -> dict:
    return {
        "type": "SEND_MESSAGE",
        "usuario": usuario,
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        "corpo_texto": corpo_texto,
    }


def format_server_event(raw_message: str) -> str:
    try:
        event = json.loads(raw_message)
    except json.JSONDecodeError:
        return raw_message

    event_type = event.get("type")

    if event_type == "MESSAGE_RECEIVED":
        payload = event.get("payload", {})
        return (
            f"[{event.get('channel_id')}] "
            f"{payload.get('usuario')}: {payload.get('corpo_texto')}"
        )

    if event_type in {"MEMBER_JOINED", "MEMBER_LEFT", "CONNECTED", "ERROR"}:
        return str(event.get("message", event))

    if event_type == "BRIEFING":
        messages = event.get("messages", [])
        return f"Briefing recebido com {len(messages)} mensagem(ns)."

    return json.dumps(event, ensure_ascii=False)


class TerminalClient:
    def __init__(
        self,
        base_url: str,
        channel_id: str,
        usuario: str,
        reconnect_delay: float = RECONNECT_DELAY_SECONDS,
    ):
        self.base_url = base_url
        self.channel_id = channel_id
        self.usuario = usuario
        self.reconnect_delay = reconnect_delay
        self.stop_event = asyncio.Event()

    async def run(self):
        input_queue: asyncio.Queue[str | None] = asyncio.Queue()
        input_task = asyncio.create_task(self._read_stdin(input_queue))

        try:
            while not self.stop_event.is_set():
                try:
                    await self._run_connected_session(input_queue)
                except (OSError, ConnectionClosed, InvalidURI) as error:
                    if self.stop_event.is_set():
                        break

                    print(
                        "Conexao perdida; reconectando automaticamente "
                        f"em {self.reconnect_delay:.0f}s. ({error})",
                        flush=True,
                    )
                    await asyncio.sleep(self.reconnect_delay)
        finally:
            input_task.cancel()

    async def _read_stdin(self, input_queue: asyncio.Queue[str | None]):
        while not self.stop_event.is_set():
            line = await asyncio.to_thread(sys.stdin.readline)

            if line == "":
                await input_queue.put(None)
                return

            await input_queue.put(line.rstrip("\r\n"))

    async def _run_connected_session(
        self,
        input_queue: asyncio.Queue[str | None],
    ):
        url = build_websocket_url(
            self.base_url,
            self.channel_id,
            self.usuario,
        )

        async with websockets.connect(url) as websocket:
            print(f"Conectado em {url}", flush=True)
            receiver_task = asyncio.create_task(self._receive(websocket))
            sender_task = asyncio.create_task(self._send(websocket, input_queue))

            done, pending = await asyncio.wait(
                {receiver_task, sender_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()

            for task in done:
                task.result()

    async def _receive(self, websocket):
        async for raw_message in websocket:
            print(format_server_event(raw_message), flush=True)

    async def _send(self, websocket, input_queue: asyncio.Queue[str | None]):
        while not self.stop_event.is_set():
            line = await input_queue.get()

            if line is None or line.strip().lower() in {"/sair", "/exit", "/quit"}:
                self.stop_event.set()
                await websocket.close()
                return

            text = line.strip()

            if not text:
                continue

            await websocket.send(json.dumps(create_message(self.usuario, text)))


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Cliente de terminal WebSocket do RescueRadio."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_BASE_URL,
        help="Base WebSocket, por exemplo ws://localhost:8000 ou ws://localhost:8001.",
    )
    parser.add_argument(
        "--channel",
        default=DEFAULT_CHANNEL_ID,
        help="Canal WebSocket.",
    )
    parser.add_argument(
        "--usuario",
        required=True,
        help="Nome do socorrista.",
    )
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None):
    args = parse_args(argv)
    client = TerminalClient(args.url, args.channel, args.usuario)
    await client.run()


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
