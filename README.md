# RescueRadio API

Backend FastAPI do RescueRadio. Ele concentra a regra operacional do radio
digital: autenticacao, usuarios, bases, perfis, ocorrencias, operacoes,
mensagens em tempo real, briefing automatico, presenca, auditoria e metricas.

A API foi organizada para que a GUI seja o fluxo principal da Entrega 3. O
console/terminal deixa de ser o meio de uso diario; HTTP e WebSocket passam a
ser as interfaces do sistema.

## Visao rapida

- Framework: FastAPI.
- Banco principal: PostgreSQL, via SQLAlchemy async.
- Presenca e fan-out entre instancias: Redis e Redis Pub/Sub.
- Chat em tempo real: WebSocket autenticado com JWT.
- Auditoria assincrona: Kafka, sem bloquear o caminho critico do chat.
- Observabilidade: endpoint `/metrics` com Prometheus.
- Fallback local: repositories em memoria quando variaveis externas nao forem
  configuradas.

## Arquitetura de pastas

```text
app/
  main.py                  # cria a aplicacao, injeta dependencias e registra routers
  config.py                # configuracoes por variaveis de ambiente
  dependencies.py          # autenticacao, autorizacao e dependencias FastAPI
  domain/
    auth.py                # roles, JWT, hash/verificacao de senha
    schemas.py             # modelos Pydantic de entrada
    validators.py          # validacao de mensagens/UDP
  routes/
    auth.py                # bootstrap, login, cadastro, /auth/me
    bases.py               # bases operacionais
    users.py               # gestao de usuarios e roles
    profiles.py            # perfil operacional do usuario autenticado
    operators.py           # consulta de operadores e presenca
    occurrences.py         # ocorrencias
    operations.py          # criacao, membros, fechamento e auditoria
    channels.py            # acoes administrativas do chat
    health.py              # healthcheck e metricas
    websockets.py          # chat e notificacoes globais
  repositories/
    messages.py            # historico/briefing de mensagens
    users.py               # usuarios e credenciais
    invites.py             # convites de cadastro
    bases.py               # bases
    profiles.py            # perfis, status e ultimo visto
    occurrences.py         # ocorrencias
    operations.py          # operacoes, membros e eventos
  services/
    message_service.py     # validacao, persistencia, broadcast e auditoria de mensagens
  infra/
    cache/presence.py      # presenca em memoria ou Redis
    db/                    # engine e tabelas
    messaging/             # Kafka, notificacoes e Pub/Sub
    observability/metrics.py
    transport/             # UDP, WebSocket manager e desconexao com grace period
```

Essa divisao ajuda a explicar o sistema por responsabilidade:

- `routes` fala HTTP/WebSocket.
- `dependencies` decide quem pode fazer o que.
- `services` executa casos de uso compartilhados.
- `repositories` persistem e recuperam dados.
- `infra` integra ferramentas externas.
- `domain` mantem contratos e regras pequenas de dominio.

## Regras de negocio principais

### Roles

- `admin`: administra o sistema todo. Gerencia usuarios, convites, bases e
  diagnostico.
- `comandante`: atua por UF. Cria/finaliza operacoes e gerencia membros dentro
  da propria UF.
- `operador`: atua na propria base e nas operacoes para as quais foi designado.

### Cadastro

O cadastro aberto foi removido. O fluxo correto e:

1. Criar o primeiro admin por bootstrap.
2. Admin cria convites.
3. Convite define role e escopo do usuario.
4. Usuario registra conta com o codigo do convite.
5. Usuario completa onboarding/perfil na GUI.

### Canais de chat

- Chat geral da base: `base:{base_id}:geral`.
- Chat de operacao: `operacao:{operation_id}`.

Ao conectar no WebSocket, o servidor envia automaticamente um `BRIEFING` com as
ultimas 50 mensagens persistidas do canal. Isso atende ao requisito de novo
socorrista receber contexto imediatamente.

### Operacoes

Uma operacao e criada a partir de uma ocorrencia e uma lista de membros. Quando
finalizada:

- o chat especifico fica somente leitura;
- novas mensagens sao rejeitadas;
- resumo, resultado e auditoria permanecem consultaveis;
- o historico usa `outcome` para diferenciar sucesso/falha.

### Concorrencia

O servidor usa locks em estados mutaveis em memoria, por exemplo:

- repositories em memoria de mensagens, perfis, operacoes, convites e usuarios;
- gerenciador de conexoes WebSocket;
- notificacoes globais;
- tarefas pendentes de desconexao.

Em producao/local completo, PostgreSQL e Redis reduzem a dependencia de memoria
local, mas os locks continuam importantes para testes, fallback e consistencia
durante uso simultaneo.

## Endpoints principais

Autenticacao:

- `POST /auth/bootstrap-admin`
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`

Usuarios, convites e perfis:

- `GET /users`
- `PATCH /users/{username}/role`
- `DELETE /users/{username}`
- `GET /invites`
- `POST /invites`
- `DELETE /invites/{invite_id}`
- `GET /profiles/me`
- `PUT /profiles/me`
- `GET /operators`

Bases e ocorrencias:

- `GET /bases`
- `POST /bases`
- `PATCH /bases/{base_id}`
- `DELETE /bases/{base_id}`
- `POST /occurrences`
- `GET /occurrences`

Operacoes:

- `POST /operations`
- `GET /operations`
- `GET /operations/{operation_id}`
- `POST /operations/{operation_id}/members`
- `POST /operations/{operation_id}/close`
- `GET /operations/{operation_id}/audit`

Chat e observabilidade:

- `DELETE /channels/{channel_id}/messages`
- `GET /health`
- `GET /metrics`

WebSockets:

- `/ws/channel/{channel_id}?token={jwt}`
- `/ws/notifications?token={jwt}`

## WebSocket do chat

Cliente envia:

```json
{
  "type": "SEND_MESSAGE",
  "usuario": "ignorado-pelo-servidor",
  "timestamp_iso": "2026-06-28T12:00:00Z",
  "corpo_texto": "Mensagem operacional"
}
```

O servidor usa o JWT para definir o usuario real. Eventos principais:

- `CONNECTED`: conexao aceita e membros ativos.
- `BRIEFING`: ultimas mensagens do canal.
- `MESSAGE_RECEIVED`: nova mensagem retransmitida.
- `MEMBER_JOINED`: operador entrou no canal.
- `MEMBER_LEFT`: operador saiu do canal.
- `CHAT_CLEARED`: admin limpou o historico do canal.
- `ERROR`: rejeicao ou falha operacional.

## WebSocket de notificacoes

O WebSocket global fica em:

```text
ws://localhost:8000/ws/notifications?token={jwt}
```

Ele envia `OPERATION_ASSIGNED` quando um operador e designado para uma
operacao. O push e melhor esforco: se o usuario estiver offline, a operacao
continua persistida e aparece quando a GUI listar operacoes ativas.

## Configuracao

Variaveis principais:

| Variavel | Finalidade | Padrao |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL async | vazio, usa memoria |
| `REDIS_URL` | Presenca e Pub/Sub | vazio, usa memoria |
| `JWT_SECRET` | Assinatura dos tokens | `rescueradio-local-secret` |
| `JWT_EXPIRE_MINUTES` | Duracao do token | `480` |
| `BOOTSTRAP_ADMIN_KEY` | Chave do primeiro admin | `rescueradio-bootstrap` |
| `CORS_ALLOW_ORIGINS` | Origens permitidas | `*` |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka para auditoria | vazio/noop |
| `KAFKA_AUDIT_TOPIC` | Topico de auditoria | `rescueradio.audit` |
| `DISCONNECT_GRACE_SECONDS` | Janela para reconexao rapida | `2` |
| `ENABLE_UDP` | Liga UDP legado | `false` |
| `UDP_HOST` / `UDP_PORT` | Endereco UDP | `0.0.0.0` / `9000` |

## Desenvolvimento local

Requisitos:

- Python 3.12.
- Opcionalmente PostgreSQL, Redis e Kafka. Sem eles, a API usa memoria.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Linux/macOS:

```bash
python -m venv .venv
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m uvicorn app.main:app --reload
```

Documentacao interativa:

- Swagger: <http://localhost:8000/docs>
- Redoc: <http://localhost:8000/redoc>
- Health: <http://localhost:8000/health>

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
```

Se uma dependencia nova foi adicionada, atualize o ambiente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Docker

Build local da imagem:

```powershell
docker build -t rescueradio-api:local .
```

Execucao isolada em memoria:

```powershell
docker run --rm -p 8000:8000 rescueradio-api:local
```

Para executar com PostgreSQL, Redis, Kafka, Kong, Web, Prometheus, Loki e
Grafana, use o repositorio `rescueradio-infra`.

## UDP legado

O UDP existe para compatibilidade com entregas anteriores e fica desligado por
padrao. Para testar, defina:

```powershell
$env:ENABLE_UDP="true"
```

Quando habilitado, datagramas JSON validos entram no mesmo fluxo do
`MessageService`: validacao, persistencia, broadcast e metricas.

## Observabilidade

O endpoint `/metrics` expoe metricas Prometheus como:

- `rescueradio_active_connections`
- `rescueradio_messages_published_total`
- `rescueradio_websocket_errors_total`
- `rescueradio_reconnections_total`
- `rescueradio_udp_events_total`
- `rescueradio_kafka_failures_total`
- `rescueradio_auth_events_total`

Logs estruturados sao usados para eventos relevantes de WebSocket, auditoria,
mensagens e conexoes quebradas.

## Fluxo manual recomendado

1. Suba o ambiente completo pelo `rescueradio-infra`.
2. Acesse a GUI em <http://localhost:4200>.
3. Configure o primeiro admin pelo bootstrap.
4. Complete o perfil operacional.
5. Crie uma base, se necessario.
6. Gere convite para operador ou comandante.
7. Abra outra aba/janela, cadastre o usuario convidado e complete onboarding.
8. Envie mensagens na Central de Comunicacao.
9. Abra nova instancia para validar briefing automatico.
10. Reinicie a API para validar reconexao silenciosa.
11. Crie/finalize uma operacao e confira historico/auditoria.
