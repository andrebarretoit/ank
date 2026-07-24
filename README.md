<div align="center">

# ANK

**Android Konteiner**

Engine de contêineres ultra-leva para Android — sem compilação, puros scripts shell + Python.

[![Shell](https://img.shields.io/badge/Shell-100%25-4EAA25?style=flat&logo=gnu-bash&logoColor=white)](https://www.gnu.org/software/bash/)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Magisk](https://img.shields.io/badge/Magisk-20.4%2B-F44336?style=flat&logo=android&logoColor=white)](https://www.magiskapp.com/)
[![License](https://img.shields.io/badge/License-AKSAL--1.0-FF6B35.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-2.0.0-2196F3)](https://github.com/andrebarretoit/ank)
[![Platform](https://img.shields.io/badge/Platform-Android-3DDC84?style=flat&logo=android&logoColor=white)](https://www.android.com/)

<br>

[andrebarreto.work](https://andrebarreto.work) · [GitHub](https://github.com/andrebarretoit) · [LinkedIn](https://linkedin.com/in/andrebarretoit)

</div>

---

# Portugues

## O que e o ANK?

**ANK** (**A**ndroid **K**onteiner) e uma engine de containeres para Android que roda containeres Linux via root do Magisk + chroot. Funciona tambem sem root via PRoot (modo Lite). Sem compilacao necessaria — tudo e scripts shell e um servidor HTTP Python com painel web estilo Portainer.

```
 ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                            ANK ENGINE                                            │
 │                                                                                                  │
 │               Web Panel (Port 8001)    │    REST API    │    Magisk Module / PRoot               │
 │              HTML/CSS/JS + xterm.js     │    Python3     │    post-fs-data / bootstrap            │
 ├──────────────────────────────────────────────────────────────────────────────────────────────────┤
 │                                    Bridge ank0 │ iptables NAT                                    │
 ├──────────────────────────────────────────────────────────────────────────────────────────────────┤
 │                          Alpine Linux (Chroot / PRoot) │ s6 process supervisor                   │
 │                          ank-alpinebase: openssh + bash + busybox + shadow + openssl + s6        │
 │                          Python 3.12 | ~20MB rootfs | SSL/TLS                                   │
 └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Tiers Enterprise (v2)

| Tag | Tier | NETNS | PIDNS | Overlay | Rede | Root |
|-----|------|:-----:|:-----:|:-------:|:----:|:----:|
| X | **Isolated** | Yes | Yes | Yes | Namespace isolada | Sim |
| Y | **Shared Network** | No | Yes | Yes | Host | Sim |
| Z | **Shared Host** | No | No | Yes | Host | Sim |
| W | **Native Host** | No | No | No | Host | Sim |
| L | **Lite** | No | No | No | Host | Nao (PRoot) |

> O ANK detecta automaticamente o tier mais alto suportado pelo kernel do device.

### Funcionalidades

- **Containeres chroot/PRoot** — Rootfs Alpine Linux com Python 3 pre-instalado
- **GUI Installer** — Instalador grafico para Windows (PySide6/Qt6 + ADB)
- **5 tiers enterprise** — Isolamento progressivo conforme capacidade do kernel
- **Modo Lite** — Funciona sem root via PRoot (userspace emulation)
- **Painel web** — UI dark estilo Portainer em `localhost:8001`
- **Terminal interativo** — xterm.js + WebSocket para host shell e terminal de container
- **SSH de containeres** — Acesso SSH direto via terminal web ou cliente SSH externo
- **Templates de imagem** — Deploy com um clique: Python, Nginx, Apache, PHP, Node.js
- **Ankfile** — Build de imagens customizadas via Ankfile (tipo Dockerfile) com suporte a `PASSWD`
- **Pull Image** — Baixe e construa imagens pelo painel web (Alpine, ank-alpinebase)
- **File Explorer** — Navegue, edite, crie, renomeie e delete arquivos dentro dos containeres
- **Upload de arquivos** — Envie sites estaticos diretamente para containeres (HTML/CSS/JS/ZIP)
- **Shell** — Comandos `ank` e `ank-core` pelo terminal web + comandos reais do host
- **Log streaming em tempo real** — Saida de build/deploy/start/stop via polling a cada 1s
- **Stats em tempo real** — CPU, memoria, uptime, status dos containeres
- **Port mapping** — Encaminhe portas do dispositivo para containeres (TCP/UDP)
- **Auto-incremento de porta** — Portas em uso sao incrementadas automaticamente (+1)
- **Autostart** — Containeres restauram no boot via Magisk
- **s6 process supervisor** — Gerenciamento de processos leve (~200KB, sem Python)
- **Seguranca** — Token Bearer, HTTPS auto-assinado, rate limiting, headers de seguranca
- **Uninstall completo** — Desinstalacao via painel com remocao total

---

### Inicio Rapido

#### GUI Installer (Recomendado — Windows)

1. Baixe `ANK-Installer.exe` em [Releases](https://github.com/andrebarretoit/ank/releases)
2. Conecte o device via USB com ADB habilitado
3. Execute o instalador — detecta device, tier, e instala automaticamente
4. Acesse `http://<ip-do-device>:8001`

#### Modulo Magisk (Manual)

1. Baixe `ank-magisk.zip` em [Releases](https://github.com/andrebarretoit/ank/releases)
2. Magisk Manager → Modulos → Instalar do armazenamento → selecione o zip
3. Reinicie
4. Abra `http://localhost:8001`
5. Login: `admin` / `admin123`

#### Modo Lite (Sem Root)

1. Baixe `ANK-Installer.exe` ou use `adb push` para enviar o rootfs + PRoot
2. Execute `ank-lite-bootstrap.sh` no device
3. Execute `start-lite.sh` para iniciar o servidor
4. Acesse `http://localhost:8001`

#### Credenciais

| Campo | Valor |
|-------|-------|
| Usuario | `admin` |
| Senha | `admin123` |

Salvas em `/data/local/ank/config.json`. Troque imediatamente via Configuracoes.

---

### Comandos CLI

#### `ank` — Shell Web

| Comando | Descricao |
|---------|-----------|
| `ank ps` | Listar containeres (nome, status, IP) |
| `ank start <nome>` | Iniciar um container |
| `ank stop <nome>` | Parar um container |
| `ank restart <nome>` | Reiniciar um container |
| `ank rm <nome>` | Deletar um container |
| `ank logs <nome>` | Ver logs do container |
| `ank exec <nome> <cmd>` | Executar comando dentro do container |
| `ank inspect <nome>` | Ver info do container (JSON) |
| `ank images` | Listar imagens baixadas |
| `ank templates` | Listar templates disponiveis |
| `ank deploy <template> <nome>` | Deploy de um template |
| `ank ankfile <nome> <arquivo>` | Build de Ankfile personalizado |
| `ank pull <image>` | Baixar imagem base |

#### `ank-core` — Administracao do Sistema

| Comando | Descricao |
|---------|-----------|
| `ank-core status` | Status da engine + contagem de containeres |
| `ank-core restart` | Reiniciar o servidor ANK |
| `ank-core shell` | Shell do host (fora do chroot) |
| `ank-core info` | Info do dispositivo (kernel, memoria, CPU) |
| `ank-core network` | Configuracao de rede |
| `ank-core clean` | Limpar containeres orfaos |
| `ank-core logs` | Ver logs do servidor |
| `ank --man <cmd>` | Ajuda detalhada de um comando |

---

### Templates de Imagem

| Template | Pacotes | Porta | Pagina ANK |
|----------|---------|-------|------------|
| Alpine 3.20 | Imagem base | — | — |
| Python 3.12 | python3, pip | 5000 | Yes |
| Nginx Static | nginx | 8080 | Yes |
| Apache Static | apache2 | 8080 | Yes |
| PHP 8.2 | php82, php82-mbstring, php82-json | 8080 | Yes |
| Node.js 20 | nodejs, npm | 3000 | Yes |

Todos os templates vem pre-configurados com software instalado e pagina ANK de exemplo.
Faca deploy pelo painel web ou via `ank deploy <template> <nome>`.

---

### Ankfile (Imagens Customizadas)

Crie imagens customizadas com um Ankfile (similar a Dockerfile).

| Instrucao | Descricao |
|-----------|-----------|
| `FROM <image>` | Imagem base (obrigatorio) |
| `RUN <cmd>` | Executar comando durante build |
| `EXPOSE <port>` | Expor porta |
| `WORKDIR <path>` | Definir diretorio de trabalho |
| `PASSWD <senha>` | Definir senha root do container |

**Exemplo:**

```dockerfile
FROM alpine-3.20
RUN apk add --allow-untrusted nginx
RUN mkdir -p /var/www/html
RUN echo "<h1>Custom ANK Image</h1>" > /var/www/html/index.html
PASSWD minhasenha123
EXPOSE 8080
```

---

### Referencia da API

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `GET` | `/api/status` | Status da engine + uptime + CPU |
| `GET` | `/api/config` | Obter config do painel |
| `POST` | `/api/config` | Atualizar config do painel |
| `GET` | `/api/containers` | Listar containeres |
| `POST` | `/api/containers` | Criar container |
| `GET` | `/api/containers/:id` | Inspecionar container |
| `GET` | `/api/containers/:id/logs` | Logs (tail 8KB) |
| `POST` | `/api/containers/:id/start` | Iniciar |
| `POST` | `/api/containers/:id/stop` | Parar |
| `POST` | `/api/containers/:id/restart` | Reiniciar |
| `POST` | `/api/containers/:id/update` | Atualizar config |
| `POST` | `/api/containers/:id/exec` | Executar comando |
| `DELETE` | `/api/containers/:id` | Deletar |
| `GET` | `/api/containers/:id/files` | Listar arquivos |
| `GET` | `/api/containers/:id/files/content` | Ler conteudo de arquivo |
| `POST` | `/api/containers/:id/files/write` | Escrever arquivo |
| `POST` | `/api/containers/:id/files/mkdir` | Criar diretorio |
| `POST` | `/api/containers/:id/files/rename` | Renomear arquivo |
| `DELETE` | `/api/containers/:id/files` | Deletar arquivo |
| `PUT` | `/api/containers/:id/upload` | Upload de arquivos |
| `GET` | `/api/images` | Listar imagens |
| `GET` | `/api/images/templates` | Listar templates |
| `POST` | `/api/images/deploy` | Deploy template |
| `POST` | `/api/images/ankfile` | Build de Ankfile |
| `POST` | `/api/images/pull` | Baixar imagem |
| `GET` | `/api/networks` | Config de rede |
| `POST` | `/api/networks` | Configurar rede |
| `GET` | `/api/system/info` | Info do dispositivo |
| `POST` | `/api/system/shell` | Executar comando shell |
| `POST` | `/api/system/uninstall` | Desinstalar ANK |
| `POST` | `/api/auth/login` | Autenticar |
| `POST` | `/api/auth/password` | Trocar credenciais |
| `GET` | `/api/logs` | Logs do servidor |
| `GET` | `/api/protocol` | Protocolo ativo (HTTP/HTTPS) |
| `WS` | `/ws/shell` | Terminal host (WebSocket) |
| `WS` | `/ws/terminal/:name` | Terminal de container (WebSocket) |

#### Exemplos curl

```bash
# Listar containeres
curl -H "Authorization: Bearer <token>" http://localhost:8001/api/containers

# Deploy de um template
curl -H "Authorization: Bearer <token>" -X POST \
  -H "Content-Type: application/json" \
  -d '{"template":"nginx-static","name":"meu-site"}' \
  http://localhost:8001/api/images/templates

# Listar arquivos de um container
curl -H "Authorization: Bearer <token>" \
  http://localhost:8001/api/containers/meu-site/files?path=/

# Baixar imagem
curl -H "Authorization: Bearer <token>" -X POST \
  -H "Content-Type: application/json" \
  -d '{"image":"alpine-3.20"}' \
  http://localhost:8001/api/images/pull
```

---

### Requisitos

| Requisito | Rooted (Full) | Sem Root (Lite) |
|-----------|---------------|-----------------|
| Android | Qualquer dispositivo com Magisk | Qualquer Android 5+ |
| Magisk | v20.4+ | Nenhum |
| Kernel | 3.10+ | N/A |
| Armazenamento | ~200MB para rootfs + containeres | ~150MB para rootfs |
| RAM | ~50MB para o servidor | ~30MB para o servidor |

---

### Estrutura do Projeto

```
ank/
├── server/
│   ├── server.py                 # Servidor HTTP Python3 (stdlib, sem Flask)
│   └── static/
│       ├── index.html            # UI do painel web
│       ├── style.css             # Tema dark/light + responsivo
│       ├── app.js                # JS client-side (xterm.js, WebSocket, modais)
│       └── favicon.svg           # Icone do app
├── magisk-module/
│   ├── module.prop               # Metadados do modulo
│   ├── post-fs-data.sh           # Hook de boot (bridge ank0, iptables)
│   ├── service.sh                # Servico de boot (inicia server)
│   ├── install.sh                # Instalador (two-path: tarball ou build from scratch)
│   ├── ankfs/                    # Rootfs pre-compilado (Alpine + Python + openssh)
│   │   └── ankcore-armv7.tar.gz  # Tarball do rootfs
│   ├── scripts/
│   │   ├── container.sh          # Ciclo de vida dos containeres + _ensure_ankbase
│   │   ├── network.sh            # Namespaces + iptables
│   │   ├── resources.sh          # Cgroups (memoria/cpu)
│   │   ├── cleanup.sh            # Garbage collector
│   │   ├── detect.sh             # Deteccao de kernel/modo
│   │   ├── download-rootfs.sh    # Download Alpine minirootfs
│   │   ├── executor.sh           # Executor de comandos
│   │   ├── build_tarball.sh      # Gerar ankcore tarball (dev tool)
│   │   ├── uninstall.sh          # Desinstalacao completa
│   │   ├── ank-lite-bootstrap.sh # Bootstrap PRoot (non-root)
│   │   ├── start-lite.sh         # Iniciar servidor Lite
│   │   └── wifi-watchdog.sh      # Watchdog de reconexao WiFi
│   └── server/                   # Copia dos arquivos do server
├── installer/
│   ├── main.py                   # Entry point do GUI installer
│   ├── ANK-Installer.spec        # PyInstaller spec
│   ├── core/
│   │   ├── adb.py                # Wrapper ADB
│   │   ├── detector.py           # Deteccao de capabilities + tier
│   │   └── installer_lite.py     # Instalacao non-root via PRoot
│   └── ui/
│       ├── app.py                # Janela principal + sidebar (PySide6/Qt6)
│       ├── theme.py              # Cores, fontes, layout
│       ├── step_connect.py       # Step 1: Conectar device
│       ├── step_detect.py        # Step 2: Detectar compatibilidade
│       ├── step_confirm.py       # Step 3: Confirmar instalacao
│       ├── step_install.py       # Step 4: Instalando
│       ├── step_reboot.py        # Step 5: Reiniciando
│       └── step_done.py          # Step 6: Finalizado
├── LICENSE                       # AKSAL-1.0
├── README.md
├── PROJECT.md                    # Spec do projeto
├── DEVELOPMENT.md                # Guia de desenvolvimento
└── build_zip.py                  # Gerador do ank-magisk.zip
```

#### Caminhos no Dispositivo

```
/data/local/ank/
├── ankfs/                        # Rootfs do servidor (Alpine + Python)
│   ├── usr/bin/python3           # Python 3.12
│   ├── usr/sbin/sshd             # OpenSSH server
│   ├── opt/ank/server.py         # Servidor ativo
│   ├── dev/                      # Device nodes (null, urandom, ptmx)
│   └── lib/ld-musl-*.so.1       # Linker musl
├── images/                       # Imagens base
│   ├── alpine-3.20/              # Alpine minirootfs limpa
│   └── ank-alpinebase/           # Base para containeres (openssh + bash + s6)
├── containers/<nome>/            # Dados por container
│   ├── config.json               # Config (status, porta, IP, password)
│   ├── merged/                   # Rootfs do container
│   ├── upper/                    # Overlay upper layer
│   └── work/                     # Overlay work layer
├── logs/                         # server.log, server.pid, <container>.log
├── cache/                        # alpine-minirootfs-<arch>.tar.gz
├── config.json                   # Config global (subnet, porta, credenciais)
├── mode                          # Tier detectado (JSON)
├── protocol                      # HTTP ou HTTPS
└── cert.pem / key.pem            # Certificado HTTPS (auto-gerado)
```

---

### Compatibilidade

| Funcionalidade | Lite (L) | Shared Host (Z) | Shared Network (Y) | Isolated (X) |
|----------------|:--------:|:---------------:|:-------------------:|:------------:|
| Chroot | PRoot | Yes | Yes | Yes |
| iptables NAT | No | Yes | Yes | Yes |
| Port Mapping | No | Yes | Yes | Yes |
| Isolamento de Rede | No | No | No | Yes (NET_NS) |
| Isolamento de PID | No | No | Yes (PID_NS) | Yes (PID_NS) |
| OverlayFS | No | Yes | Yes | Yes |
| cgroups | No | Yes | Yes | Yes |
| Sem Root | Yes | No | No | No |

> O tier e determinado automaticamente pelo `detect.sh` conforme as capabilities do kernel.

---

### Versoes

| Versao | Status | Download |
|--------|--------|----------|
| v2.0.0 | **Ultima** | [ank-magisk.zip](https://github.com/andrebarretoit/ank/releases/download/v2.0.0/ank-magisk.zip) + [ANK-Installer.exe](https://github.com/andrebarretoit/ank/releases/download/v2.0.0/ANK-Installer.exe) |

---

### Solucao de Problemas

```bash
# Verificar suporte a namespaces no kernel
adb shell su -c "zcat /proc/config.gz | grep NAMESPACES"

# Verificar suporte a OverlayFS no kernel
adb shell su -c "zcat /proc/config.gz | grep OVERLAY"

# Verificar tier detectado
adb shell cat /data/local/ank/mode

# Logs do servidor
adb shell cat /data/local/ank/logs/server.log

# Logs de um container
adb shell cat /data/local/ank/logs/<nome>.log

# Verificar se ank-alpinebase existe
adb shell su -c "ls /data/local/ank/images/ank-alpinebase/bin/sh"

# Recriar ank-alpinebase (lazy build)
adb shell su -c "rm -rf /data/local/ank/images/ank-alpinebase"

# Verificar device nodes no ankfs
adb shell su -c "ls -la /data/local/ank/ankfs/dev/"

# Testar Python no ankfs
adb shell su -c "mount -t proc proc /data/local/ank/ankfs/proc; chroot /data/local/ank/ankfs /usr/bin/python3 -c 'import pty; print(\"OK\")'"

# Limpeza manual
adb shell su -c "sh /data/local/ank/scripts/cleanup.sh"
```

---

### Licenca

[![License: AKSAL-1.0](https://img.shields.io/badge/License-AKSAL--1.0-FF6B35.svg)](LICENSE)

**Android Konteiner Source Available License 1.0** — uso livre para qualquer proposito. Nao e permitido vender ou distribuir o software. Veja [LICENSE](LICENSE) para detalhes.

---

**ANK** — Containeres no Android. Sem PC necessaria.

**Criado por [Andre Barreto](https://github.com/andrebarretoit)** · [GitHub](https://github.com/andrebarretoit) · [LinkedIn](https://linkedin.com/in/andrebarretoit) · [andrebarreto.work](https://andrebarreto.work)

---
---

# English

## What is ANK?

**ANK** (**A**ndroid **K**onteiner) is a container engine for Android that runs Linux containers via Magisk root + chroot. Also works without root via PRoot (Lite mode). No compilation needed — everything is shell scripts and a Python HTTP server with a Portainer-style web panel.

```
 ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                            ANK ENGINE                                            │
 │                                                                                                  │
 │               Web Panel (Port 8001)    │    REST API    │    Magisk Module / PRoot               │
 │              HTML/CSS/JS + xterm.js     │    Python3     │    post-fs-data / bootstrap            │
 ├──────────────────────────────────────────────────────────────────────────────────────────────────┤
 │                                    Bridge ank0 │ iptables NAT                                    │
 ├──────────────────────────────────────────────────────────────────────────────────────────────────┤
 │                          Alpine Linux (Chroot / PRoot) │ s6 process supervisor                   │
 │                          ank-alpinebase: openssh + bash + busybox + shadow + openssl + s6        │
 │                          Python 3.12 | ~20MB rootfs | SSL/TLS                                   │
 └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Enterprise Tiers (v2)

| Tag | Tier | NETNS | PIDNS | Overlay | Network | Root |
|-----|------|:-----:|:-----:|:-------:|:-------:|:----:|
| X | **Isolated** | Yes | Yes | Yes | Isolated namespace | Yes |
| Y | **Shared Network** | No | Yes | Yes | Host | Yes |
| Z | **Shared Host** | No | No | Yes | Host | Yes |
| W | **Native Host** | No | No | No | Host | Yes |
| L | **Lite** | No | No | No | Host | No (PRoot) |

> ANK automatically detects the highest tier supported by the device kernel.

### Features

- **Chroot/PRoot containers** — Alpine Linux rootfs with Python 3 pre-installed
- **GUI Installer** — Graphical installer for Windows (PySide6/Qt6 + ADB)
- **5 enterprise tiers** — Progressive isolation based on kernel capability
- **Lite mode** — Works without root via PRoot (userspace emulation)
- **Web panel** — Portainer-style dark UI on `localhost:8001`
- **Interactive terminal** — xterm.js + WebSocket for host shell and container terminal
- **Container SSH** — Direct SSH access via web terminal or external SSH client
- **Image templates** — One-click deploy: Python, Nginx, Apache, PHP, Node.js
- **Ankfile** — Build custom images from Ankfile (like Dockerfile) with `PASSWD` support
- **Pull Image** — Download and build images from the web panel (Alpine, ank-alpinebase)
- **File Explorer** — Browse, edit, create, rename and delete files inside containers
- **File upload** — Upload static sites directly to containers (HTML/CSS/JS/ZIP)
- **Shell** — `ank` and `ank-core` commands from the web terminal + real host commands
- **Realtime log streaming** — Build/deploy/start/stop output via 1s polling
- **Realtime stats** — CPU, memory, uptime, container status
- **Port mapping** — Forward device ports to containers (TCP/UDP)
- **Auto port increment** — Conflicting ports auto-increment (+1)
- **Auto-start** — Containers restore on boot via Magisk
- **s6 process supervisor** — Lightweight process management (~200KB, no Python)
- **Security** — Token Bearer auth, self-signed HTTPS, rate limiting, security headers
- **Complete uninstall** — Uninstall via panel with full removal

---

### Quick Start

#### GUI Installer (Recommended — Windows)

1. Download `ANK-Installer.exe` from [Releases](https://github.com/andrebarretoit/ank/releases)
2. Connect device via USB with ADB enabled
3. Run the installer — detects device, tier, and installs automatically
4. Access `http://<device-ip>:8001`

#### Magisk Module (Manual)

1. Download `ank-magisk.zip` from [Releases](https://github.com/andrebarretoit/ank/releases)
2. Magisk Manager → Modules → Install from storage → select the zip
3. Reboot
4. Open `http://localhost:8001`
5. Login: `admin` / `admin123`

#### Lite Mode (No Root)

1. Download `ANK-Installer.exe` or use `adb push` to send rootfs + PRoot
2. Run `ank-lite-bootstrap.sh` on the device
3. Run `start-lite.sh` to start the server
4. Access `http://localhost:8001`

#### Credentials

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `admin123` |

Saved to `/data/local/ank/config.json`. Change immediately via Settings.

---

### CLI Commands

#### `ank` — Web Shell

| Command | Description |
|---------|-------------|
| `ank ps` | List containers (name, status, IP) |
| `ank start <name>` | Start a container |
| `ank stop <name>` | Stop a container |
| `ank restart <name>` | Restart a container |
| `ank rm <name>` | Delete a container |
| `ank logs <name>` | View container logs |
| `ank exec <name> <cmd>` | Execute command inside container |
| `ank inspect <name>` | Show container info (JSON) |
| `ank images` | List downloaded images |
| `ank templates` | List available templates |
| `ank deploy <template> <name>` | Deploy a template |
| `ank ankfile <name> <file>` | Build from custom Ankfile |
| `ank pull <image>` | Download base image |

#### `ank-core` — System Admin

| Command | Description |
|---------|-------------|
| `ank-core status` | Engine status + container counts |
| `ank-core restart` | Restart the ANK server |
| `ank-core shell` | Host shell (outside chroot) |
| `ank-core info` | Device info (kernel, memory, CPU) |
| `ank-core network` | Network configuration |
| `ank-core clean` | Clean orphaned containers |
| `ank-core logs` | View server logs |
| `ank --man <cmd>` | Detailed help for a command |

---

### Image Templates

| Template | Packages | Port | ANK Page |
|----------|----------|------|----------|
| Alpine 3.20 | Base image | — | — |
| Python 3.12 | python3, pip | 5000 | Yes |
| Nginx Static | nginx | 8080 | Yes |
| Apache Static | apache2 | 8080 | Yes |
| PHP 8.2 | php82, php82-mbstring, php82-json | 8080 | Yes |
| Node.js 20 | nodejs, npm | 3000 | Yes |

All templates come pre-configured with software installed and an ANK branded example page.
Deploy from the web panel or via `ank deploy <template> <name>`.

---

### Ankfile (Custom Images)

Create custom images with an Ankfile (similar to Dockerfile).

| Instruction | Description |
|-------------|-------------|
| `FROM <image>` | Base image (required) |
| `RUN <cmd>` | Execute command during build |
| `EXPOSE <port>` | Expose port |
| `WORKDIR <path>` | Set working directory |
| `PASSWD <password>` | Set container root password |

**Example:**

```dockerfile
FROM alpine-3.20
RUN apk add --allow-untrusted nginx
RUN mkdir -p /var/www/html
RUN echo "<h1>Custom ANK Image</h1>" > /var/www/html/index.html
PASSWD mysecretpass
EXPOSE 8080
```

---

### API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | Engine status + uptime + CPU |
| `GET` | `/api/config` | Get panel configuration |
| `POST` | `/api/config` | Update panel config |
| `GET` | `/api/containers` | List containers |
| `POST` | `/api/containers` | Create container |
| `GET` | `/api/containers/:id` | Inspect container |
| `GET` | `/api/containers/:id/logs` | Logs (tail 8KB) |
| `POST` | `/api/containers/:id/start` | Start |
| `POST` | `/api/containers/:id/stop` | Stop |
| `POST` | `/api/containers/:id/restart` | Restart |
| `POST` | `/api/containers/:id/update` | Update settings |
| `POST` | `/api/containers/:id/exec` | Execute command |
| `DELETE` | `/api/containers/:id` | Delete |
| `GET` | `/api/containers/:id/files` | List files |
| `GET` | `/api/containers/:id/files/content` | Read file content |
| `POST` | `/api/containers/:id/files/write` | Write file |
| `POST` | `/api/containers/:id/files/mkdir` | Create directory |
| `POST` | `/api/containers/:id/files/rename` | Rename file |
| `DELETE` | `/api/containers/:id/files` | Delete file |
| `PUT` | `/api/containers/:id/upload` | Upload files |
| `GET` | `/api/images` | List images |
| `GET` | `/api/images/templates` | List templates |
| `POST` | `/api/images/deploy` | Deploy template |
| `POST` | `/api/images/ankfile` | Build from Ankfile |
| `POST` | `/api/images/pull` | Download image |
| `GET` | `/api/networks` | Network config |
| `POST` | `/api/networks` | Configure network |
| `GET` | `/api/system/info` | Device info |
| `POST` | `/api/system/shell` | Execute shell command |
| `POST` | `/api/system/uninstall` | Uninstall ANK |
| `POST` | `/api/auth/login` | Authenticate |
| `POST` | `/api/auth/password` | Change credentials |
| `GET` | `/api/logs` | Server logs |
| `GET` | `/api/protocol` | Active protocol (HTTP/HTTPS) |
| `WS` | `/ws/shell` | Host terminal (WebSocket) |
| `WS` | `/ws/terminal/:name` | Container terminal (WebSocket) |

#### curl Examples

```bash
# List containers
curl -H "Authorization: Bearer <token>" http://localhost:8001/api/containers

# Deploy a template
curl -H "Authorization: Bearer <token>" -X POST \
  -H "Content-Type: application/json" \
  -d '{"template":"nginx-static","name":"my-site"}' \
  http://localhost:8001/api/images/templates

# List files in a container
curl -H "Authorization: Bearer <token>" \
  http://localhost:8001/api/containers/my-site/files?path=/

# Download an image
curl -H "Authorization: Bearer <token>" -X POST \
  -H "Content-Type: application/json" \
  -d '{"image":"alpine-3.20"}' \
  http://localhost:8001/api/images/pull
```

---

### Requirements

| Requirement | Rooted (Full) | No Root (Lite) |
|------------|---------------|-----------------|
| Android | Any device with Magisk | Any Android 5+ |
| Magisk | v20.4+ | None |
| Kernel | 3.10+ | N/A |
| Storage | ~200MB for rootfs + containers | ~150MB for rootfs |
| RAM | ~50MB for the server | ~30MB for the server |

---

### Project Structure

```
ank/
├── server/
│   ├── server.py                 # Python3 HTTP server (stdlib, no Flask)
│   └── static/
│       ├── index.html            # Web panel UI
│       ├── style.css             # Dark/light theme + responsive
│       ├── app.js                # Client-side JS (xterm.js, WebSocket, modals)
│       └── favicon.svg           # App icon
├── magisk-module/
│   ├── module.prop               # Module metadata
│   ├── post-fs-data.sh           # Boot hook (bridge ank0, iptables)
│   ├── service.sh                # Boot service (starts server)
│   ├── install.sh                # Installer (two-path: tarball or build from scratch)
│   ├── ankfs/                    # Pre-built rootfs (Alpine + Python + openssh)
│   │   └── ankcore-armv7.tar.gz  # Rootfs tarball
│   ├── scripts/
│   │   ├── container.sh          # Container lifecycle + _ensure_ankbase
│   │   ├── network.sh            # Namespaces + iptables
│   │   ├── resources.sh          # Cgroups (memory/cpu)
│   │   ├── cleanup.sh            # Garbage collector
│   │   ├── detect.sh             # Kernel/mode detection
│   │   ├── download-rootfs.sh    # Download Alpine minirootfs
│   │   ├── executor.sh           # Command executor
│   │   ├── build_tarball.sh      # Generate ankcore tarball (dev tool)
│   │   ├── uninstall.sh          # Complete uninstaller
│   │   ├── ank-lite-bootstrap.sh # PRoot bootstrap (non-root)
│   │   ├── start-lite.sh         # Start Lite server
│   │   └── wifi-watchdog.sh      # WiFi reconnect watchdog
│   └── server/                   # Server files copy
├── installer/
│   ├── main.py                   # GUI installer entry point
│   ├── ANK-Installer.spec        # PyInstaller spec
│   ├── core/
│   │   ├── adb.py                # ADB wrapper
│   │   ├── detector.py           # Capability detection + tier
│   │   └── installer_lite.py     # Non-root install via PRoot
│   └── ui/
│       ├── app.py                # Main window + sidebar (PySide6/Qt6)
│       ├── theme.py              # Colors, fonts, layout
│       ├── step_connect.py       # Step 1: Connect device
│       ├── step_detect.py        # Step 2: Detect compatibility
│       ├── step_confirm.py       # Step 3: Confirm installation
│       ├── step_install.py       # Step 4: Installing
│       ├── step_reboot.py        # Step 5: Rebooting
│       └── step_done.py          # Step 6: Done
├── LICENSE                       # AKSAL-1.0
├── README.md
├── PROJECT.md                    # Project spec
├── DEVELOPMENT.md                # Development guide
└── build_zip.py                  # ank-magisk.zip builder
```

#### Device Paths

```
/data/local/ank/
├── ankfs/                        # Server rootfs (Alpine + Python)
│   ├── usr/bin/python3           # Python 3.12
│   ├── usr/sbin/sshd             # OpenSSH server
│   ├── opt/ank/server.py         # Live server
│   ├── dev/                      # Device nodes (null, urandom, ptmx)
│   └── lib/ld-musl-*.so.1       # Musl linker
├── images/                       # Base images
│   ├── alpine-3.20/              # Clean Alpine minirootfs
│   └── ank-alpinebase/           # Container base (openssh + bash + s6)
├── containers/<name>/            # Per-container data
│   ├── config.json               # Config (status, port, IP, password)
│   ├── merged/                   # Container rootfs
│   ├── upper/                    # Overlay upper layer
│   └── work/                     # Overlay work layer
├── logs/                         # server.log, server.pid, <container>.log
├── cache/                        # alpine-minirootfs-<arch>.tar.gz
├── config.json                   # Global config (subnet, port, credentials)
├── mode                          # Detected tier (JSON)
├── protocol                      # HTTP or HTTPS
└── cert.pem / key.pem            # HTTPS certificate (auto-generated)
```

---

### Compatibility

| Feature | Lite (L) | Shared Host (Z) | Shared Network (Y) | Isolated (X) |
|---------|:--------:|:---------------:|:-------------------:|:------------:|
| Chroot | PRoot | Yes | Yes | Yes |
| iptables NAT | No | Yes | Yes | Yes |
| Port Mapping | No | Yes | Yes | Yes |
| Network Isolation | No | No | No | Yes (NET_NS) |
| PID Isolation | No | No | Yes (PID_NS) | Yes (PID_NS) |
| OverlayFS | No | Yes | Yes | Yes |
| cgroups | No | Yes | Yes | Yes |
| No Root Required | Yes | No | No | No |

> Tier is automatically determined by `detect.sh` based on kernel capabilities.

---

### Releases

| Version | Status | Download |
|---------|--------|----------|
| v2.0.0 | **Latest** | [ank-magisk.zip](https://github.com/andrebarretoit/ank/releases/download/v2.0.0/ank-magisk.zip) + [ANK-Installer.exe](https://github.com/andrebarretoit/ank/releases/download/v2.0.0/ANK-Installer.exe) |

---

### Troubleshooting

```bash
# Check kernel namespace support
adb shell su -c "zcat /proc/config.gz | grep NAMESPACES"

# Check kernel OverlayFS support
adb shell su -c "zcat /proc/config.gz | grep OVERLAY"

# Check detected tier
adb shell cat /data/local/ank/mode

# Server logs
adb shell cat /data/local/ank/logs/server.log

# Container logs
adb shell cat /data/local/ank/logs/<name>.log

# Check if ank-alpinebase exists
adb shell su -c "ls /data/local/ank/images/ank-alpinebase/bin/sh"

# Rebuild ank-alpinebase (lazy build)
adb shell su -c "rm -rf /data/local/ank/images/ank-alpinebase"

# Verify device nodes in ankfs
adb shell su -c "ls -la /data/local/ank/ankfs/dev/"

# Test Python in ankfs
adb shell su -c "mount -t proc proc /data/local/ank/ankfs/proc; chroot /data/local/ank/ankfs /usr/bin/python3 -c 'import pty; print(\"OK\")'"

# Manual cleanup
adb shell su -c "sh /data/local/ank/scripts/cleanup.sh"
```

---

### License

[![License: AKSAL-1.0](https://img.shields.io/badge/License-AKSAL--1.0-FF6B35.svg)](LICENSE)

**Android Konteiner Source Available License 1.0** — free to use for any purpose. Selling or distributing the software is not permitted. See [LICENSE](LICENSE) for details.

---

**ANK** — Containers on Android. No PC needed.

**Created by [Andre Barreto](https://github.com/andrebarretoit)** · [GitHub](https://github.com/andrebarretoit) · [LinkedIn](https://linkedin.com/in/andrebarretoit) · [andrebarreto.work](https://andrebarreto.work)
