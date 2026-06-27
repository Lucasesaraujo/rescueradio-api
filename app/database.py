from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    func,
)


metadata = MetaData()


def create_channel_messages_table() -> Table:
    existing_table = metadata.tables.get("channel_messages")

    if existing_table is not None:
        return existing_table

    return Table(
        "channel_messages",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("channel_id", String(120), nullable=False, index=True),
        Column("type", String(40), nullable=False),
        Column("usuario", String(80), nullable=False),
        Column("timestamp_iso", String(40), nullable=False),
        Column("corpo_texto", Text, nullable=False),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            index=True,
        ),
    )


def create_users_table() -> Table:
    existing_table = metadata.tables.get("users")

    if existing_table is not None:
        return existing_table

    return Table(
        "users",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("username", String(80), nullable=False, unique=True, index=True),
        Column("display_name", String(120), nullable=False),
        Column("password_hash", Text, nullable=False),
        Column("role", String(40), nullable=False),
        Column("base_id", String(80), nullable=True, index=True),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )


def create_invites_table() -> Table:
    existing_table = metadata.tables.get("invites")

    if existing_table is not None:
        return existing_table

    return Table(
        "invites",
        metadata,
        Column("id", String(80), primary_key=True),
        Column("code_hash", Text, nullable=False, unique=True, index=True),
        Column("base_id", String(80), nullable=False, index=True),
        Column("role", String(40), nullable=False),
        Column("expires_at", DateTime(timezone=True), nullable=True),
        Column("used_by", String(80), nullable=True),
        Column("used_at", DateTime(timezone=True), nullable=True),
        Column("revoked_at", DateTime(timezone=True), nullable=True),
        Column("created_by", String(80), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


def create_bases_table() -> Table:
    existing_table = metadata.tables.get("bases")

    if existing_table is not None:
        return existing_table

    return Table(
        "bases",
        metadata,
        Column("id", String(80), primary_key=True),
        Column("name", String(120), nullable=False),
        Column("city", String(120), nullable=False),
        Column("latitude", Float, nullable=True),
        Column("longitude", Float, nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


def create_base_coverage_cities_table() -> Table:
    existing_table = metadata.tables.get("base_coverage_cities")

    if existing_table is not None:
        return existing_table

    return Table(
        "base_coverage_cities",
        metadata,
        Column("base_id", String(80), nullable=False),
        Column("city", String(120), nullable=False),
        PrimaryKeyConstraint("base_id", "city"),
    )


def create_operator_functions_table() -> Table:
    existing_table = metadata.tables.get("operator_functions")

    if existing_table is not None:
        return existing_table

    return Table(
        "operator_functions",
        metadata,
        Column("id", String(80), primary_key=True),
        Column("label", String(120), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


def create_operator_profiles_table() -> Table:
    existing_table = metadata.tables.get("operator_profiles")

    if existing_table is not None:
        return existing_table

    return Table(
        "operator_profiles",
        metadata,
        Column("username", String(80), ForeignKey("users.username"), primary_key=True),
        Column("full_name", String(160), nullable=True),
        Column("callsign", String(40), nullable=True, index=True),
        Column("operational_name", String(120), nullable=False),
        Column("base_id", String(80), nullable=False, index=True),
        Column("function", String(120), nullable=False),
        Column("contact", String(120), nullable=False),
        Column("status", String(40), nullable=False),
        Column("connection_status", String(40), nullable=False, server_default="offline"),
        Column("last_seen_at", DateTime(timezone=True), nullable=True),
        Column("skills", Text, nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


def create_occurrences_table() -> Table:
    existing_table = metadata.tables.get("occurrences")

    if existing_table is not None:
        return existing_table

    return Table(
        "occurrences",
        metadata,
        Column("id", String(80), primary_key=True),
        Column("base_id", String(80), nullable=False, index=True),
        Column("title", String(160), nullable=False),
        Column("type", String(80), nullable=False),
        Column("priority", String(40), nullable=False),
        Column("status", String(40), nullable=False, index=True),
        Column("address_text", String(240), nullable=False),
        Column("latitude", Float, nullable=False),
        Column("longitude", Float, nullable=False),
        Column("description", Text, nullable=False),
        Column("created_by", String(80), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


def create_operations_table() -> Table:
    existing_table = metadata.tables.get("operations")

    if existing_table is not None:
        return existing_table

    return Table(
        "operations",
        metadata,
        Column("id", String(80), primary_key=True),
        Column("occurrence_id", String(80), nullable=False, index=True),
        Column("base_id", String(80), nullable=False, index=True),
        Column("channel_id", String(120), nullable=False, unique=True, index=True),
        Column("status", String(40), nullable=False, index=True),
        Column("created_by", String(80), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("closed_by", String(80), nullable=True),
        Column("closed_at", DateTime(timezone=True), nullable=True),
        Column("closing_summary", Text, nullable=True),
        Column("outcome", String(40), nullable=True),
    )


def create_operation_members_table() -> Table:
    existing_table = metadata.tables.get("operation_members")

    if existing_table is not None:
        return existing_table

    return Table(
        "operation_members",
        metadata,
        Column("operation_id", String(80), nullable=False),
        Column("username", String(80), nullable=False),
        Column("display_name", String(120), nullable=False),
        Column("assigned_by", String(80), nullable=False),
        Column("joined_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        PrimaryKeyConstraint("operation_id", "username"),
    )


def create_operation_status_events_table() -> Table:
    existing_table = metadata.tables.get("operation_status_events")

    if existing_table is not None:
        return existing_table

    return Table(
        "operation_status_events",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("operation_id", String(80), nullable=False, index=True),
        Column("status", String(40), nullable=False),
        Column("username", String(80), nullable=False),
        Column("note", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
