# Protocolo UDP

A API escuta datagramas JSON na porta `9000/udp`. O transporte UDP funciona
somente como entrada de mensagens: não há ACK, resposta ao remetente ou
registro de presença.

## Datagrama

```json
{
  "type": "SEND_MESSAGE",
  "channel_id": "canal-geral",
  "usuario": "Lucas",
  "timestamp_iso": "2026-06-09T12:00:00Z",
  "corpo_texto": "Equipe Alfa chegou ao local."
}
```

O campo `channel_id` identifica o canal de destino. Os demais campos seguem
as mesmas validações do protocolo WebSocket.

Quando o datagrama é válido, a API:

1. remove `channel_id` do conteúdo da mensagem;
2. adiciona a mensagem ao briefing do canal;
3. envia um evento `MESSAGE_RECEIVED` aos clientes WebSocket daquele canal.

Datagramas inválidos são registrados no log e descartados.

A publicação usa uma fila limitada a 100 datagramas. Quando a fila está
cheia, novos datagramas são descartados com aviso no log para impedir criação
ilimitada de tarefas e consumo excessivo de memória.

## Teste manual no PowerShell

```powershell
$udp = [System.Net.Sockets.UdpClient]::new()
$payload = @{
  type = "SEND_MESSAGE"
  channel_id = "canal-geral"
  usuario = "Central"
  timestamp_iso = [DateTime]::UtcNow.ToString("o")
  corpo_texto = "Mensagem enviada por UDP."
} | ConvertTo-Json -Compress
$bytes = [Text.Encoding]::UTF8.GetBytes($payload)
$udp.Send($bytes, $bytes.Length, "localhost", 9000)
$udp.Dispose()
```
