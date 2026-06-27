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


class RegisterRequest(BaseModel):
    username: UserName
    password: str = Field(min_length=6, max_length=120)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    invite_code: str = Field(min_length=8, max_length=120)


class BootstrapAdminRequest(BaseModel):
    username: UserName
    password: str = Field(min_length=6, max_length=120)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    bootstrap_key: str = Field(min_length=1, max_length=240)


class LoginRequest(BaseModel):
    username: UserName
    password: str = Field(min_length=1, max_length=120)


class BaseCreateRequest(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=120)
    uf: str = Field(default="PE", min_length=2, max_length=2)
    latitude: float | None = None
    longitude: float | None = None
    coverage_cities: list[str] = Field(default_factory=list)


class BaseUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=120)
    uf: str = Field(default="PE", min_length=2, max_length=2)
    latitude: float | None = None
    longitude: float | None = None
    coverage_cities: list[str] = Field(default_factory=list)


class InviteCreateRequest(BaseModel):
    base_id: str | None = Field(default=None, min_length=1, max_length=80)
    uf_scope: str | None = Field(default=None, min_length=2, max_length=2)
    role: str = Field(default="operador", min_length=1, max_length=40)
    expires_in_hours: int | None = Field(default=72, ge=1, le=24 * 30)


class ProfileRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    callsign: str | None = Field(default=None, min_length=1, max_length=40)
    operational_name: str = Field(min_length=1, max_length=120)
    base_id: str = Field(min_length=1, max_length=80)
    function: str = Field(default="", max_length=120)
    contact: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    status: str = Field(default="disponivel", min_length=1, max_length=40)
    skills: list[str] = Field(default_factory=list)


class UserRoleUpdateRequest(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    base_id: str | None = Field(default=None, max_length=80)
    uf_scope: str | None = Field(default=None, min_length=2, max_length=2)


class OccurrenceCreateRequest(BaseModel):
    base_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    type: str = Field(min_length=1, max_length=80)
    priority: str = Field(min_length=1, max_length=40)
    address_text: str = Field(min_length=1, max_length=240)
    latitude: float
    longitude: float
    description: str = Field(default="", max_length=2000)


class OperationCreateRequest(BaseModel):
    occurrence: OccurrenceCreateRequest
    member_usernames: list[str] = Field(default_factory=list)


class OperationMembersRequest(BaseModel):
    usernames: list[str] = Field(default_factory=list)


class OperationCloseRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    outcome: str = Field(pattern="^(success|failure)$")
