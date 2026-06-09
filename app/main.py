import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from app.message_service import MessageService
from app.state import ChannelState
from app.udp import UdpMessageProtocol
from app.websocket_manager import WebSocketConnectionManager


def create_app(
    udp_host: str | None = None,
    udp_port: int | None = None,
) -> FastAPI:
    channel_state = ChannelState()
    connections = WebSocketConnectionManager()
    message_service = MessageService(channel_state, connections)
    configured_host = udp_host or os.getenv("UDP_HOST", "0.0.0.0")
    configured_port = (
        udp_port
        if udp_port is not None
        else int(os.getenv("UDP_PORT", "9000"))
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: UdpMessageProtocol(message_service),
            local_addr=(configured_host, configured_port),
        )
        app.state.udp_transport = transport
        app.state.udp_protocol = protocol
        app.state.udp_port = transport.get_extra_info("sockname")[1]

        try:
            yield
        finally:
            transport.close()

    app = FastAPI(title="RescueRadio API", lifespan=lifespan)
    app.state.channel_state = channel_state
    app.state.connections = connections
    app.state.message_service = message_service

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "rescueradio-api",
            "transports": ["http", "websocket", "udp"],
        }

    @app.websocket("/ws/channel/{channel_id}")
    async def websocket_endpoint(
        websocket: WebSocket,
        channel_id: str,
        usuario: str = Query(...),
    ):
        await connections.connect(channel_id, usuario, websocket)

        await websocket.send_json({
            "type": "CONNECTED",
            "channel_id": channel_id,
            "usuario": usuario,
            "message": "Conectado ao canal com sucesso.",
        })
        await websocket.send_json({
            "type": "BRIEFING",
            "channel_id": channel_id,
            "messages": channel_state.get_briefing(channel_id),
        })
        await connections.broadcast(channel_id, {
            "type": "MEMBER_JOINED",
            "channel_id": channel_id,
            "usuario": usuario,
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "members": connections.get_active_members(channel_id),
            "message": f"{usuario} entrou no canal.",
        })

        try:
            while True:
                data = await websocket.receive_json()
                is_valid, result = await message_service.publish(
                    channel_id,
                    data,
                )

                if not is_valid:
                    await websocket.send_json({
                        "type": "ERROR",
                        "channel_id": channel_id,
                        "message": result,
                    })
        except WebSocketDisconnect:
            disconnected = connections.disconnect(
                channel_id,
                usuario,
                websocket,
            )

            if disconnected:
                await connections.broadcast(channel_id, {
                    "type": "MEMBER_LEFT",
                    "channel_id": channel_id,
                    "usuario": usuario,
                    "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                    "members": connections.get_active_members(channel_id),
                    "message": f"{usuario} saiu do canal.",
                })

    return app


app = create_app()
