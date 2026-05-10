# 🐠 Aquarium Light Controller

Controlador de iluminação para aquário marinho com transições graduais (dimmer suave) usando controladores **Magic Home Wi-Fi**.

## O que faz

- Controla 3 canais independentes: **Azul**, **Branco** e **UV**
- Transições graduais entre níveis (curva cosseno — suave como nascer/pôr do sol)
- Dashboard web para visualizar a curva e editar a agenda
- Gráfico em tempo real mostrando a curva de 24h
- Roda em Docker — ideal para Raspberry Pi, NAS ou qualquer servidor

## Início Rápido

### 1. Clone ou copie os arquivos

```
aquarium-light-controller/
├── controller.py
├── Dockerfile
├── docker-compose.yml
└── web/
    └── index.html
```

### 2. Configure o IP do controlador

Edite o `docker-compose.yml` ou configure depois pelo dashboard web.

Pra descobrir o IP do seu controlador Magic Home:
- Abra o app Magic Home Pro → configurações do dispositivo → veja o IP
- Ou no terminal: `pip install flux_led && flux_led -s`

### 3. Suba com Docker

```bash
docker compose up -d --build
```

### 4. Acesse o dashboard

Abra no navegador: `http://<IP-DO-SERVIDOR>:8080`

## Configuração

### Via Dashboard Web (recomendado)

- Acesse `http://<IP>:8080`
- Ajuste os horários e intensidades com os sliders
- O gráfico atualiza em tempo real
- Clique em "Salvar"

### Via arquivo JSON

O config fica em `/data/config.json` dentro do container (volume `aquarium_data`).

```json
{
  "controller_ip": "192.168.1.100",
  "transition_minutes": 30,
  "update_interval_seconds": 10,
  "schedule": [
    {"time": "07:00", "blue": 25, "white": 0, "uv": 15, "label": "Amanhecer"},
    {"time": "10:00", "blue": 60, "white": 50, "uv": 50, "label": "Manhã"},
    {"time": "12:00", "blue": 80, "white": 100, "uv": 80, "label": "Pico"},
    {"time": "15:00", "blue": 60, "white": 50, "uv": 50, "label": "Tarde"},
    {"time": "17:00", "blue": 35, "white": 10, "uv": 25, "label": "Entardecer"},
    {"time": "18:30", "blue": 0, "white": 0, "uv": 0, "label": "Desligado"}
  ]
}
```

### Mapeamento de canais

Por padrão, o controlador mapeia:
- **Canal R** (Red) → LEDs Azuis
- **Canal G** (Green) → LEDs Brancos  
- **Canal B** (Blue) → LEDs UV

Se a sua luminária tiver mapeamento diferente, ajuste o `channel_map` no config.

### Parâmetros

| Parâmetro | Descrição | Padrão |
|-----------|-----------|--------|
| `controller_ip` | IP do controlador Magic Home na rede | `192.168.1.100` |
| `transition_minutes` | Duração de cada transição gradual | `30` |
| `update_interval_seconds` | Intervalo entre atualizações de brilho | `10` |

## Como funciona a transição

Em vez de mudar o brilho de uma vez, o controller usa uma **curva cosseno** para fazer a transição suave:

```
Nível
100% ─────────────────────╮
                       ╭───╯
                    ╭──╯
                 ╭──╯
  25% ───────────╯
       07:00  07:15  07:30  08:00  10:00
             ←── 30 min ──→
```

A curva cosseno acelera suavemente no início, mantém velocidade constante no meio, e desacelera ao chegar no nível alvo — muito mais natural que uma rampa linear.

## API

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/state` | GET | Estado atual (níveis, status, erros) |
| `/api/config` | GET | Configuração completa |
| `/api/config` | POST | Atualizar configuração |
| `/api/preview` | GET | Curva de 24h (para o gráfico) |
| `/api/reconnect` | POST | Forçar reconexão ao controlador |

## Portainer

Para deploy via Portainer:

1. Vá em **Stacks** → **Add Stack**
2. Cole o conteúdo do `docker-compose.yml`
3. Ou use **Git Repository** apontando pro repo
4. Deploy

## Troubleshooting

- **"Disconnected"**: Verifique se o IP está correto e o controlador está na mesma rede
- **Transições não funcionam**: O script precisa estar rodando continuamente — o Docker garante isso
- **Chip BL602**: Modelos mais novos do Magic Home usam chip BL602 em vez de ESP. O flux_led funciona com ambos via protocolo de rede (não precisa flashear)
