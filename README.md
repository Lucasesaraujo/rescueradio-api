# RescueRadio API

Backend FastAPI do RescueRadio, responsavel por autenticacao, comunicacao em
tempo real, persistencia, presenca, metricas e auditoria.

## Responsabilidades

- cadastro por convite com JWT;
- bootstrap controlado do primeiro `admin`;
- perfis operacionais por usuario;
- gestao de bases, ocorrencias, operacoes e membros;
- WebSocket autenticado por canal;
- briefing automatico com as ultimas 50 mensagens;
- broadcast em tempo real;
- persistencia de mensagens e usuarios no PostgreSQL;
- presenca online em Redis;
- Redis Pub/Sub para broadcast entre instancias;
- locks em estados mutaveis em memoria;
- auditoria assincrona em Kafka;
- endpoint `/metrics` para Prometheus.

## Desenvolvimento

Requisitos:

- Python 3.12;
- PostgreSQL, Redis e Kafka quando as variaveis de ambiente estiverem definidas.

```bash
python -m venv .venv
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
```

Sem `DATABASE_URL`, `REDIS_URL` e `KAFKA_BOOTSTRAP_SERVERS`, a API usa
repositorios em memoria, presenca em memoria e auditoria noop. Isso facilita
testes locais rapidos.

## Variaveis principais

| Variavel | Uso |
| --- | --- |
| `DATABASE_URL` | PostgreSQL para mensagens e usuarios |
| `REDIS_URL` | Presenca e Pub/Sub |
| `JWT_SECRET` | Assinatura dos tokens JWT |
| `JWT_EXPIRE_MINUTES` | Expiracao do token, padrao 480 |
| `BOOTSTRAP_ADMIN_KEY` | Chave para criar o primeiro admin, padrao `rescueradio-bootstrap` |
| `KAFKA_BOOTSTRAP_SERVERS` | Bootstrap Kafka para auditoria |
| `KAFKA_AUDIT_TOPIC` | Topico de auditoria, padrao `rescueradio.audit` |
| `CORS_ALLOW_ORIGINS` | Origens liberadas para a GUI |
| `ENABLE_UDP` | Habilita transporte UDP legado quando `true`, padrao `false` |
| `UDP_HOST` / `UDP_PORT` | Endereco UDP legado, padrao `0.0.0.0:9000` |

## Autenticacao

Bootstrap do primeiro admin:

```http
POST /auth/bootstrap-admin
Content-Type: application/json

{
  "username": "admin",
  "password": "segredo123",
  "display_name": "Admin",
  "bootstrap_key": "rescueradio-bootstrap"
}
```

Depois que existir um admin, novos cadastros exigem convite de uso unico.
Convites sao criados por admin:

```http
POST /invites
Authorization: Bearer <token-admin>
Content-Type: application/json

{
  "base_id": "base-central",
  "role": "operador",
  "expires_in_hours": 72
}
```

Cadastro com convite:

```http
POST /auth/register
Content-Type: application/json

{
  "username": "lucas",
  "password": "segredo123",
  "display_name": "Lucas",
  "invite_code": "codigo-do-convite"
}
```

Login:

```http
POST /auth/login
Content-Type: application/json

{
  "username": "lucas",
  "password": "segredo123"
}
```

O login retorna:

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "user": {
    "username": "lucas",
    "display_name": "Lucas",
    "role": "admin"
  }
}
```

Consulta da sessao:

```http
GET /auth/me
Authorization: Bearer <token>
```

## WebSocket

Endpoint:

```text
ws://localhost:8000/ws/channel/{channel_id}?token={jwt}
```

Notificacoes globais autenticadas:

```text
ws://localhost:8000/ws/notifications?token={jwt}
```

Quando uma operacao e criada ou um operador e adicionado, o servidor envia
`OPERATION_ASSIGNED` para o usuario designado conectado. O push nao substitui
persistencia: se o operador estiver offline, a operacao aparece na listagem ao
entrar.

Eventos enviados pelo servidor:

- `CONNECTED`;
- `BRIEFING`;
- `MESSAGE_RECEIVED`;
- `MEMBER_JOINED`;
- `MEMBER_LEFT`;
- `ERROR`.

O usuario exibido no chat e derivado do JWT. Mesmo que o cliente envie outro
`usuario` dentro do payload, o servidor substitui pelo usuario autenticado.

## Dominio operacional

Endpoints principais:

- `GET /bases`, `POST /bases`, `PATCH /bases/{id}` e `DELETE /bases/{id}`;
- `GET /profiles/me` e `PUT /profiles/me`;
- `GET /operators?base_id=&status=&skill=`;
- `GET /users` e `PATCH /users/{username}/role`;
- `POST /occurrences` e `GET /occurrences`;
- `POST /operations`, `GET /operations`, `GET /operations/{id}`;
- `POST /operations/{id}/members`;
- `POST /operations/{id}/close` com `outcome: "success" | "failure"`;
- `GET /operations/{id}/audit`.

O sistema cria automaticamente a base `base-central` quando o schema e
inicializado. Canais de chat usam:

- `base:{base_id}:geral` para o chat permanente da base;
- `operacao:{operation_id}` para o chat da operacao.

Quando uma operacao e finalizada, o canal especifico passa a rejeitar novas
mensagens e o endpoint de auditoria preserva ocorrencia, participantes,
mensagens, eventos de status, resultado formal e resumo de encerramento.

## UDP legado opcional

O fluxo principal da Entrega 3 e a GUI via HTTP/WebSocket. O transporte UDP de
entregas anteriores fica desabilitado por padrao e pode ser ligado com
`ENABLE_UDP=true` para testes especificos. Quando habilitado, a API recebe
datagramas JSON em `9000/udp`:

```json
{
  "type": "SEND_MESSAGE",
  "channel_id": "canal-geral",
  "usuario": "Central",
  "timestamp_iso": "2026-06-09T12:00:00Z",
  "corpo_texto": "Mensagem enviada por UDP."
}
```

Mensagens validas entram no mesmo historico persistente e sao retransmitidas
para clientes WebSocket do canal.

## Observabilidade

O endpoint Prometheus fica em:

```text
GET /metrics
```

Metricas principais:

- `rescueradio_active_connections`;
- `rescueradio_messages_published_total`;
- `rescueradio_websocket_errors_total`;
- `rescueradio_reconnections_total`;
- `rescueradio_udp_events_total`, apenas quando o legado UDP for usado;
- `rescueradio_kafka_failures_total`;
- `rescueradio_auth_events_total`.

Eventos de auditoria sao publicados no Kafka sem bloquear o chat. Se o Kafka
ficar indisponivel, a falha e registrada em logs/metricas e a mensagem continua
seguindo para o historico e para o WebSocket.

## Testes

```bash
python -m pytest
```

## Docker

Para executar a arquitetura completa com PostgreSQL, Redis, Kafka, Kong,
Prometheus, Loki, Grafana e frontend, use o repositorio `rescueradio-infra`.
