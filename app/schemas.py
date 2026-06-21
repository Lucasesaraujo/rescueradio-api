from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


UserName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]


class IncomingMessage(BaseModel):
    type: str
    usuario: UserName
    timestamp_iso: str
    corpo_texto: str = Field(min_length=1, max_length=500)


class UdpDatagram(BaseModel):
    channel_id: str = Field(min_length=1, max_length=120)
