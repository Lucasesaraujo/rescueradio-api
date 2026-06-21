# Persistencia e Estado Temporario

O estado atual e dividido entre mensagens persistidas, presenca temporaria e
conexoes WebSocket locais.

## Mensagens e Briefing

Em ambiente completo, mensagens recebidas por WebSocket e UDP passam pelo
`MessageService`, sao validadas e gravadas na tabela `channel_messages` do
PostgreSQL.

Campos principais:

- `id`;
- `channel_id`;
- `type`;
- `usuario`;
- `timestamp_iso`;
- `corpo_texto`;
- `created_at`.

Quando um cliente WebSocket entra em um canal, a API consulta as ultimas 50
mensagens persistidas daquele canal e envia o evento `BRIEFING`.

Nos testes automatizados, a API usa `InMemoryMessageRepository` quando
`DATABASE_URL` nao esta configurado. Esse fallback existe para manter a suite
unitaria leve e nao substitui o PostgreSQL no Docker Compose.

## Presenca

A presenca dos membros online fica no Redis, separada por canal:

```text
presence:canal-geral -> Lucas, Marcelo
```

Entradas e saidas WebSocket atualizam o Redis e geram os eventos
`MEMBER_JOINED` e `MEMBER_LEFT` com a lista atualizada de membros online.
Remetentes UDP nao aparecem como membros ativos porque nao mantem sessao com a
API.

Nos testes automatizados, a API usa `InMemoryPresenceService` quando `REDIS_URL`
nao esta configurado.

## Conexoes WebSocket

`WebSocketConnectionManager` continua mantendo os objetos WebSocket locais ao
processo para realizar o broadcast aos clientes conectados naquela instancia da
API.

Esta etapa nao usa Redis Pub/Sub. Portanto, PostgreSQL e Redis ja removem a
perda de historico e centralizam presenca, mas multiplas instancias da API
ainda nao compartilham broadcast em tempo real.
