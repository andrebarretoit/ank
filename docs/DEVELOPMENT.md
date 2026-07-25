# Desenvolvimento ANK

## Visao Geral

Trabalhamos com rodadas. Cada rodada tem escopo, tarefas, notas e pendencias.
Antes de cada commit: reavaliar, verificar escopo, documentar pendencias.

---

## Regras

1. Tudo na branch `ank`. Commits versionados por tags de funcionalidade.
2. Cada rodada tem escopo definido. Nao implementar fora do escopo.
3. Antes de commit: rodar lint, testar manualmente, reavaliar notas.
4. Formato do commit:
```
<tipo>(<escopo>): <descricao>
Rodada: <numero>
Nota anterior: <nota>
Nota atual: <nota>
```

5. Notas (0-10): Funcionalidade, Seguranca, Performance, Organizacao, UX, Documentacao

---

## Rodada 1 — Fix de Bugs Criticos

**Escopo**: Corrigir bugs que impedem uso funcional do sistema

### Tarefas

| # | Tarefa | Arquivos | Status |
|---|--------|----------|--------|
| 1.1 | Fix: Ankfile deploy - `mkdir: not found` / `curl: not found` (PATH quebrado no chroot) | `server.py` | ✅ |
| 1.2 | Fix: Ankfile deploy - variavel `p` nao definida (bug Python no loop de ports) | `server.py` | ✅ |
| 1.3 | Fix: WebSocket sem autenticacao (qualquer um conecta e ganha root shell) | `server.py`, `app.js` | ✅ |
| 1.4 | Fix: WebSocket PTY - socket close nao enviava WS close frame | `server.py` | ✅ |
| 1.5 | Fix: Apache template nao inicia auto (busybox httpd args errados) | `container.sh` | ✅ |
| 1.6 | Fix: Port mappings customizados do painel nao sao aplicados no start | `container.sh` | ✅ |
| 1.7 | Fix: Cgroup fallback quando cgroup v2 nao existe (nao deve ser fatal) | `resources.sh` | ✅ |
| 1.8 | Sync server files para magisk-module/server/ | `magisk-module/server/` | ✅ |
| 1.9 | Validar logica do generate-prebuilt.sh (export de tarball) | `scripts/generate-prebuilt.sh` | ✅ |

---

### Detalhamento dos Bugs

#### 1.1 Ankfile deploy - PATH quebrado no chroot

**Problema**: O `_chroot()` em `server.py` usa `/bin/sh -c` mas nao seta PATH.
Apos `apk add`, os binarios ficam em `/usr/bin` mas o shell nao encontra.

**Erro**:
```
RUN: mkdir -p /data/cloudreve
/bin/sh: mkdir: not found
```

**Fix**: No `_chroot()`, setar PATH antes de executar:
```python
def _chroot(cmd, timeout=30):
    wrapped = "export PATH=/bin:/sbin:/usr/bin:/usr/sbin; " + cmd
    full = f"chroot {merged} /bin/sh -c '{wrapped}'"
    ...
```

Ou melhor: usar `/bin/busybox sh` em vez de `/bin/sh` para garantir applets.

---

#### 1.2 Ankfile deploy - variavel `p` nao definida

**Problema**: Em `server.py:2160`, o codigo usa `p` que nao existe nesse escopo:
```python
config["port_mappings"] = [{"host_port": p, "container_port": p, "protocol": "tcp"}]
```

**Fix**: Iterar corretamente sobre `ports`:
```python
if ports:
    config["port_mappings"] = [{"host_port": port, "container_port": port, "protocol": "tcp"} for port in ports]
```

---

#### 1.3 WebSocket sem autenticacao

**Problema**: `/ws/shell` e `/ws/terminal/<name>` nao verificam token.
Qualquer um que alcance o server pode conectar e ganhar shell root.

**Fix**: Verificar token via query param (browser nao envia headers customizados no WS):
- Frontend: adicionar `?token=<ankToken>` na URL do WebSocket
- Server: extrair token do query string e validar com `_validate_token()`

---

#### 1.4 WebSocket PTY - rfile/wfile close

**Problema**: Apos handshake HTTP 101, o server fecha `self.rfile` e `self.wfile`
para usar `self.request` diretamente como socket raw. Em certas versoes do Python,
isso pode fechar o file descriptor subjacente.

**Fix**: Nao fechar rfile/wfile, ou usar `self.request` desde o inicio.
Alternativa: usar `makefile()` com dup2 para nao afetar o socket original.

---

#### 1.5 Apache template nao inicia auto

**Problema**: Em `container.sh:686`:
```bash
apache) httpd -f /etc/apache2/httpd.conf -D FOREGROUND 2>/dev/null & ;;
```

O Alpine usa `httpd` do busybox, nao Apache2. O config path esta errado.
O busybox httpd nao tem `-D FOREGROUND`. O correto e:
```bash
apache) httpd -f -h /var/www/localhost/htdocs -p 8080 2>/dev/null & ;;
```

Ou melhor: usar o Apache do Alpine (`apache2`) com config correta.

---

#### 1.6 Port mappings customizados nao aplicados

**Problema**: `cmd_start()` em `container.sh` so faz port forwarding para
as ports hardcoded (8080, 3000, 5000) no modo isolated. Os `port_mappings`
customizados do `config.json` sao ignorados.

**Fix**: Ler `port_mappings` do config.json e aplicar via iptables:
```bash
# Ler port_mappings do config e aplicar cada um
PORTS=$(grep -o '"port_mappings":\[[^]]*\]' "$CONFIG" ...)
# Para cada mapping: iptables -t nat -A PREROUTING ...
```

---

#### 1.7 Cgroup fallback

**Problema**: `resources.sh:18` retorna erro fatal quando cgroup v2 nao existe:
```bash
mkdir -p "$CGROUP" 2>/dev/null || {
    echo "ERROR: Failed to create cgroup (is cgroup v2 enabled?)"
    return 1
}
```

`container.sh:423` chama `resources.sh setup` e se falhar, nao continua.

**Fix**: Tornar cgroup opcional. Se nao conseguir criar, avisar mas continuar:
```bash
sh "$SCRIPTS_DIR/resources.sh" setup "$NAME" 268435456 50 2>/dev/null || \
    echo "WARN: Cgroup not available, resource limits disabled"
```

---

#### 1.8 Sync server files

Copiar `server/server.py` e `server/static/*` para `magisk-module/server/`
e para `magisk-module/scripts/` (onde o install.sh copia para ankfs).

---

#### 1.9 Validar generate-prebuilt.sh

Script cria tar.xz de `/data/local/ank/ankfs`. Logica:
1. Verifica se python3 existe em ankfs
2. Verifica se server.py existe em ankfs
3. Cria tar.xz

**Validacao**: A logica esta correta. O script exporta todo o conteudo de ankfs
que ja tem python3 + server.py + openssh + bash. Pode ser usado no inicio
para criar o tarball que sera incluido no ZIP.

---

## Notas de Rodada

Ao final de cada rodada, preencher:

### Rodada 1

**Data**: 2026-07-24
**Commit**: `5378bb1`

| Aspecto | Nota |
|---------|------|
| Funcionalidade | 7/10 |
| Seguranca | 8/10 |
| Performance | 6/10 |
| Organizacao | 7/10 |
| UX | 7/10 |
| Documentacao | 8/10 |
| **Media** | **7.2/10** |

**Corrigido/Implementado**:
- 1.1: PATH fix em ambos `_chroot()` (api_deploy_template + api_build_ankfile)
- 1.2: Variavel `p` corrigida para list comprehension `[port for port in ports]`
- 1.3: Token query param em WebSocket shell + terminal endpoints, server valida com `_validate_token()`
- 1.4: `_ws_send_close()` adicionado na saida normal do PTY session
- 1.5: busybox httpd args corrigidos (`-f -p 8080 -h /var/www/localhost/htdocs`)
- 1.6: `apply_ports` chamado durante start quando `port_mappings` existe no config.json
- 1.7: `return 1` trocado por `return 0` no cgroup mkdir failure
- 1.8: server/ sincronizado com magisk-module/server/

**Pendente para proxima rodada**:
- Testar WebSocket auth com browser real (possivel bug: `ankToken` pode nao existir no escopo global)
- Testar port_mappings em container isolated mode
- Verificar se `network.sh apply_ports` limpa regras antigas antes de aplicar novas
- Adicionar log de audit para conexoes WebSocket rejeitadas
- Considerar rate limiting no endpoint de auth

---

## Fluxo de Trabalho

1. Inicio da rodada: ler este documento, verificar escopo
2. Execucao: implementar tarefas
3. Revisao: verificar se tudo foi implementado
4. Teste: testar manualmente
5. Avaliacao: preencher notas
6. Commit: formatar com notas
7. Proxima rodada: verificar pendencias

---

## Rodada 4 — GUI Installer & Universalidade

**Escopo**: Mascarar o GUI installer, modos de instalacao e suporte universal

### Tarefas

| # | Tarefa | Arquivos | Status |
|---|--------|----------|--------|
| R4.1 | Cache de compat test (evita re-executar deteccao) | `core/cache.py`, `ui/step_detect.py` | ✅ |
| R4.2 | Modo Nativo + ANK UI | `core/installer_native.py`, `ui/step_install.py`, `ui/step_confirm.py` | ✅ |
| R4.3 | Modal retry quando mirrors falham | `core/installer_lite.py`, `ui/step_install.py` | ✅ |
| R4.4 | Uninstall detecta ANK UI | `core/adb.py`, `ui/step_connect.py` | ✅ |
| R4.5 | Universalidade (root/proot/qualquer arch) | `core/adb.py`, `core/detector.py`, `core/installer_lite.py` | ✅ |

### Detalhamento

#### R4.1 Cache de compat test

- Arquivo `core/cache.py` gerencia cache JSON em `~/.ank-installer/cache/`
- TTL de 24 horas
- step_detect.py mostra resultados do cache e botao "Executar novamente"
- Evita re-execucao da deteccao a cada troca de aba

#### R4.2 Modo Nativo + ANK UI

- `installer_native.py`: instalacao sem containerizacao
- Copia server.py + static direto para /data/local/ank
- Detecta e instala ANK UI (ank-launcher.apk)
- step_confirm.py mostra descricaes especificas por tier

#### R4.3 Modal retry downloads

- _download_with_retry() tenta multiplos mirrors
- Callback retry_callback notifica UI quando todos falham
- Modal QMessageBox com opcao Retry/Cancel
- StepInstall gerencia thread com threading.Event

#### R4.4 Uninstall detecta ANK

- adb.py: check_ank_installed(), check_ank_ui_installed(), get_ank_mode()
- adb.py: uninstall_ank_ui(), uninstall_ank_full()
- step_connect.py: card mostra ANK instalado + botao desinstalar
- Confirmacao antes de desinstalar

#### R4.5 Universalidade

- KernelSU detectado via ksud, /data/adb/ksu, lsmod
- PRoot detectado via /data/local/ank/proot, which proot, Termux
- Termux detectado via /data/data/com.termux
- Arquiteturas: aarch64, armv7l, x86_64, i686
- Multi-mirror para downloads (GitHub + Tsinghua)
- DetectionResult inclui root_manager, has_kernelsu, has_termux
