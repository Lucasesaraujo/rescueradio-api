# Estado em memória

O estado atual é dividido entre mensagens dos canais e conexões WebSocket.

## Buffer de mensagens

`ChannelState` mantém um `deque(maxlen=50)` por canal. O buffer é usado para
enviar o briefing quando um cliente WebSocket entra no canal.

```python
message_buffer = {
    "canal-geral": deque(maxlen=50)
}
```

Mensagens recebidas por WebSocket e UDP passam pelo mesmo `MessageService` e
são adicionadas ao buffer somente após validação.

## Conexões e presença

`WebSocketConnectionManager` mantém as conexões por canal e usuário:

```python
connections = {
    "canal-geral": {
        "Lucas": websocket
    }
}
```

A lista de membros ativos é derivada dessas conexões. Remetentes UDP não são
registrados como membros porque não mantêm uma sessão com a API.

## Limitações

- os dados são perdidos ao reiniciar a API;
- não há histórico persistente;
- múltiplas instâncias ainda não compartilham estado;
- conexões e buffers são locais ao processo.

Persistência e estado distribuído aguardam a especificação de PostgreSQL,
Redis ou Kafka.
