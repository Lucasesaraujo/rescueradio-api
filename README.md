# RescueRadio API

Backend de comunicacao do RescueRadio, implementado com Python e FastAPI.

## Responsabilidades

- health check HTTP;
- conexoes WebSocket por canal;
- broadcast de mensagens;
- buffer circular e briefing;
- presenca de membros;
- validacao do protocolo;
- entrada de mensagens por UDP;
- futuramente, JWT, PostgreSQL, Redis e Kafka.

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

- `main`: versões estáveis;
- `develop`: integração das funcionalidades aprovadas;
- `feature/*`: desenvolvimento isolado, sempre criado a partir de `develop`.

As branches de funcionalidade devem voltar para `develop` por pull request
após a aprovação do CI.
