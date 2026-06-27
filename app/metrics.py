from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest


ACTIVE_CONNECTIONS = Gauge(
    "rescueradio_active_connections",
    "Quantidade de conexoes WebSocket ativas.",
    ["channel_id"],
)
MESSAGES_PUBLISHED = Counter(
    "rescueradio_messages_published_total",
    "Total de mensagens publicadas.",
    ["channel_id", "source"],
)
WEBSOCKET_ERRORS = Counter(
    "rescueradio_websocket_errors_total",
    "Total de erros de WebSocket ou validacao.",
    ["reason"],
)
RECONNECTIONS = Counter(
    "rescueradio_reconnections_total",
    "Total de reconexoes detectadas pelo servidor.",
    ["channel_id"],
)
UDP_EVENTS = Counter(
    "rescueradio_udp_events_total",
    "Eventos recebidos pelo transporte UDP.",
    ["result"],
)
KAFKA_FAILURES = Counter(
    "rescueradio_kafka_failures_total",
    "Falhas ao publicar auditoria no Kafka.",
)
AUTH_EVENTS = Counter(
    "rescueradio_auth_events_total",
    "Eventos de autenticacao.",
    ["result"],
)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
