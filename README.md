# RescueRadio API

Backend de comunicacao do RescueRadio, implementado com Python e FastAPI.

## Responsabilidades

- health check HTTP;
- conexoes WebSocket por canal;
- broadcast de mensagens;
- buffer circular e briefing;
- presenca de membros;
- validacao do protocolo;
- futuramente, transporte UDP, JWT, PostgreSQL, Redis e Kafka.

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

A porta UDP `9000` esta reservada para a implementacao exigida nas proximas entregas. O transporte ainda nao esta implementado.

## Documentacao

- [Protocolo WebSocket](docs/protocol.md)
- [Estado em memoria](docs/in-memory-state.md)
- [Exemplos de mensagens](docs/sample-messages.md)

Para executar o ambiente completo, use o repositorio `rescueradio-infra`.
