from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
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
