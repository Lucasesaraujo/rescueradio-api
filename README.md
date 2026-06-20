# RescueRadio API

Backend de comunicacao do RescueRadio, implementado com Python e FastAPI.

## Responsabilidades

- health check HTTP;
- conexoes WebSocket por canal;
- broadcast de mensagens;
- cliente de terminal com reconexao automatica;
- buffer circular e briefing;
- presenca de membros;
- validacao do protocolo;
- entrada de mensagens por UDP;
- futuramente, JWT, PostgreSQL, Redis e Kafka.

## Decisao tecnologica

A API utiliza Python 3.12 com FastAPI, Uvicorn e Pydantic. O FastAPI foi
escolhido porque oferece suporte nativo a operacoes assincronas e WebSocket,
adequadas para manter varias conexoes simultaneas e transmitir eventos em
tempo real. O Pydantic centraliza a tipagem e a validacao dos payloads, enquanto
o modelo assincrono do Python permite integrar a escuta UDP ao mesmo servico
sem recorrer a sockets TCP puros.

Na arquitetura do RescueRadio, esta API recebe conexoes HTTP e WebSocket
encaminhadas pelo Kong, mantem o estado temporario dos canais em memoria e
tambem recebe datagramas UDP na porta `9000`. Mensagens validas vindas de ambos
os transportes passam pelo mesmo servico de publicacao antes de entrar no
historico e serem retransmitidas aos clientes.

## Estado em memoria e briefing

Cada canal possui um buffer circular implementado com `deque(maxlen=50)`.
Portanto, sao mantidas somente as ultimas 50 mensagens validas de cada canal.
Quando um socorrista estabelece uma nova conexao WebSocket, o servidor envia
esse historico no evento `BRIEFING`.

As conexoes ativas sao organizadas por canal e usuario. A entrada de uma
conexao gera o evento `MEMBER_JOINED`, e a desconexao gera `MEMBER_LEFT`, ambos
com a lista atualizada de membros online.

## Protocolo WebSocket

O cliente envia mensagens JSON com o seguinte contrato:

```json
{
  "type": "SEND_MESSAGE",
  "usuario": "Lucas",
  "timestamp_iso": "2026-06-04T21:30:00Z",
  "corpo_texto": "Equipe Alfa chegou ao ponto de encontro."
}
```

O modelo de dominio da mensagem e
`{usuario, timestamp_iso, corpo_texto}`. O campo adicional
`type: SEND_MESSAGE` identifica o comando dentro do protocolo.

O nome do usuario deve conter de 1 a 80 caracteres uteis. Espacos externos
sao removidos, e conexoes com nome vazio ou acima do limite sao rejeitadas com
o codigo WebSocket `1008`. Frames que nao contenham JSON valido recebem
`ERROR` sem encerrar a conexao.

Eventos enviados pelo servidor:

- `CONNECTED`: confirma a conexao;
- `BRIEFING`: envia ate 50 mensagens anteriores do canal;
- `MESSAGE_RECEIVED`: retransmite uma mensagem valida;
- `MEMBER_JOINED`: informa a entrada de um socorrista;
- `MEMBER_LEFT`: informa a saida de um socorrista;
- `ERROR`: informa um payload invalido.

O contrato completo e os exemplos de payload estao em
[docs/protocol.md](docs/protocol.md).

Mensagens `SEND_MESSAGE` recebidas por WebSocket sao enviadas para os outros
socorristas conectados ao mesmo canal. O remetente nao recebe eco da propria
mensagem. Eventos de sistema, como entrada e saida de membros, continuam sendo
enviados para todos os membros conectados ao canal.

## Estrutura de pastas

```text
rescueradio-api/
|-- app/                  # API, estado, validadores e transportes
|   `-- terminal_client.py # cliente WebSocket via terminal
|-- docs/                 # protocolo e modelagem do estado
|-- tests/                # testes de WebSocket, validacao e UDP
|-- Dockerfile
|-- requirements.txt      # dependencias de execucao
|-- requirements-dev.txt  # dependencias de desenvolvimento e testes
`-- README.md
```

## Desenvolvimento

Requisitos:

- Python 3.12.

Crie um ambiente virtual, instale as dependencias e execute a API:

```bash
python -m venv .venv
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
```

O health check fica disponivel em <http://localhost:8000/health>.

O endpoint WebSocket e:

```text
ws://localhost:8000/ws/channel/{channel_id}?usuario={usuario}
```

## Cliente de terminal

Este cliente existe para validar a Entrega 2 em um nivel mais baixo, via
console, sem substituir a interface grafica do RescueRadio. A aplicacao Angular
usa o mesmo endpoint e o mesmo protocolo WebSocket descritos aqui.

Com a API em execucao, abra tres terminais de cliente e conecte tres
socorristas ao mesmo canal:

```bash
python -m app.terminal_client --usuario Lucas
```

```bash
python -m app.terminal_client --usuario Marcelo
```

```bash
python -m app.terminal_client --usuario Julia
```

Digite uma mensagem em qualquer terminal e pressione Enter. Os outros dois
terminais devem receber a mensagem imediatamente no formato:

```text
[canal-geral] Lucas: Equipe Alfa chegou ao local.
```

O terminal que enviou a mensagem nao recebe eco da propria mensagem. Para sair
do cliente, digite `/sair`, `/exit` ou `/quit`.

O cliente tenta reconectar automaticamente quando a conexao cai. Para testar
via Kong no ambiente Docker Compose, informe a URL do gateway:

```bash
python -m app.terminal_client --url ws://localhost:8001 --usuario Lucas
```

O servidor emite logs estruturados no console para conexoes, desconexoes,
mensagens recebidas, broadcasts, payloads invalidos e conexoes quebradas
removidas.

## Testes

```bash
python -m pytest
```

## Docker

```bash
docker build -t rescueradio-api:local .
docker run --rm -p 8000:8000 -p 9000:9000/udp rescueradio-api:local
```

A API recebe datagramas JSON em `9000/udp`. Mensagens válidas entram no
buffer do canal e são retransmitidas aos clientes WebSocket. Nesta fase, o
transporte UDP não envia ACK nem mantém presença.

## Documentacao

- [Protocolo WebSocket](docs/protocol.md)
- [Estado em memoria](docs/in-memory-state.md)
- [Exemplos de mensagens](docs/sample-messages.md)
- [Protocolo UDP](docs/udp.md)

Para executar o ambiente completo, use o repositorio `rescueradio-infra`.

## Fluxo de desenvolvimento

- `main`: homologação das versões aprovadas em `develop`;
- `develop`: desenvolvimento e integração das funcionalidades aprovadas;
- `feature/*`: desenvolvimento isolado, sempre criado a partir de `develop`.

As branches de funcionalidade devem voltar para `develop` por pull request
após a aprovação do CI. A promoção para homologação ocorre por pull request
de `develop` para `main`.
