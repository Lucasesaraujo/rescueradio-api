# Protocolo de Comunicacao

Este documento registra o protocolo WebSocket do RescueRadio. Para entrada de
mensagens por datagramas, consulte [Protocolo UDP](udp.md).

## Endpoint

```text
ws://localhost:8001/ws/channel/{channel_id}?usuario={usuario}
```

Na execucao com Docker Compose, o cliente usa o Kong em `localhost:8001`.

Parametros:

| Campo | Origem | Descricao |
| --- | --- | --- |
| `channel_id` | path | Identificador do canal. Na interface atual, o valor padrao e `canal-geral`. |
| `usuario` | query | Nome do socorrista, com 1 a 80 caracteres apos remover espacos externos. |

Conexoes com `usuario` vazio, formado somente por espacos ou com mais de 80
caracteres uteis sao rejeitadas durante o handshake com o codigo WebSocket
`1008`.

## Mensagem Enviada Pelo Cliente

```json
{
  "type": "SEND_MESSAGE",
  "usuario": "Lucas",
  "timestamp_iso": "2026-06-04T21:30:00Z",
  "corpo_texto": "Equipe Alfa chegou ao ponto de encontro."
}
```

Validacoes principais:

- `type` deve ser `SEND_MESSAGE`;
- `usuario` e obrigatorio, tem seus espacos externos removidos e deve conter
  de 1 a 80 caracteres;
- `timestamp_iso` deve estar em formato ISO 8601;
- `corpo_texto` e obrigatorio e deve ter ate 500 caracteres.

Se um frame de texto nao contiver JSON valido, o servidor envia `ERROR` e
mantem a conexao aberta para que o cliente possa corrigir a mensagem.

## Eventos Enviados Pelo Servidor

### `CONNECTED`

Confirma que a conexao WebSocket foi aceita.

```json
{
  "type": "CONNECTED",
  "channel_id": "canal-geral",
  "usuario": "Lucas",
  "message": "Conectado ao canal com sucesso."
}
```

### `BRIEFING`

Envia as ultimas mensagens persistidas do canal.

```json
{
  "type": "BRIEFING",
  "channel_id": "canal-geral",
  "messages": []
}
```

### `MESSAGE_RECEIVED`

Retransmite uma mensagem valida para os outros membros conectados ao canal. O
remetente WebSocket nao recebe eco da propria mensagem.

```json
{
  "type": "MESSAGE_RECEIVED",
  "channel_id": "canal-geral",
  "payload": {
    "type": "SEND_MESSAGE",
    "usuario": "Lucas",
    "timestamp_iso": "2026-06-04T21:30:00Z",
    "corpo_texto": "Equipe Alfa chegou ao ponto de encontro."
  }
}
```

### `MEMBER_JOINED`

Informa que um membro entrou no canal e envia a lista atual de membros.

```json
{
  "type": "MEMBER_JOINED",
  "channel_id": "canal-geral",
  "usuario": "Lucas",
  "timestamp_iso": "2026-06-04T21:30:00Z",
  "members": [
    {
      "usuario": "Lucas",
      "status": "online"
    }
  ],
  "message": "Lucas entrou no canal."
}
```

### `MEMBER_LEFT`

Informa que um membro saiu do canal e envia a lista atualizada de membros.

```json
{
  "type": "MEMBER_LEFT",
  "channel_id": "canal-geral",
  "usuario": "Lucas",
  "timestamp_iso": "2026-06-04T21:35:00Z",
  "members": [],
  "message": "Lucas saiu do canal."
}
```

### `ERROR`

Indica que o payload enviado pelo cliente e invalido.

```json
{
  "type": "ERROR",
  "channel_id": "canal-geral",
  "message": "Payload invalido"
}
```

Para JSON sintaticamente invalido, `message` recebe
`Payload deve conter JSON valido`.
