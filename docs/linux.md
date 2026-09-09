# Artemis no Linux

Guia da porta para Linux (Wayland e X11). O restante do app funciona igual ao
Windows; o que muda está aqui.

## Requisitos

```bash
sudo usermod -aG input $USER      # ler /dev/input e escrever em /dev/uinput
sudo apt install wl-clipboard     # ou xclip/xsel, em sessão X11
```

O grupo `input` só passa a valer depois de **logout e login** — não basta
abrir outro terminal. Sem ele o Artemis sobe, mas avisa que não consegue ler
o teclado.

Para escrever em `/dev/uinput` (a colagem e a reemissão de teclas), uma regra
udev resolve de vez:

```
# /etc/udev/rules.d/99-artemis-uinput.rules
KERNEL=="uinput", GROUP="input", MODE="0660"
```

## Como abrir o app

Na primeira execução o Artemis instala um atalho no menu de aplicativos
(`~/.local/share/applications/artemis-dictation.desktop`) e o ícone em
`~/.local/share/icons/hicolor/`. A partir daí:

- **Menu de aplicativos → Artemis Dictation** — sobe o app. Se ele já estiver
  rodando, abre a janela de configurações em vez de subir uma segunda cópia.
- **Botão direito no ícone do dock → Configurações**.
- `python -m artemis --settings` faz a mesma coisa pelo terminal.

O pedido viaja por um socket Unix no namespace abstrato, o mesmo que garante
instância única.

## A tecla do atalho não vaza mais

Ler `/dev/input` não esconde a tecla de ninguém: sem mais nada, a combinação
chega **também** na aplicação em foco. Com a tecla de ditado do MX Keys Mini,
que manda `Super+H`, isso digitava um `h` no meio do texto ditado.

Por isso o Artemis captura com exclusividade (`EVIOCGRAB`) os teclados capazes
de disparar algum atalho configurado, e devolve ao sistema, por um teclado
virtual em `/dev/uinput`, tudo que **não** for atalho. Consequências:

- Só as teclas do atalho somem; o resto passa direto, inclusive `Ctrl+C`,
  `Ctrl+Alt+F2` e um toque no `Super` sozinho.
- Teclados que não conseguem formar nenhum atalho (controles de mídia, botão
  de energia) não são capturados.
- Se o Artemis morrer, o kernel desfaz a captura sozinho.

Para desligar: **Configurações → Comportamento → _Impedir que a tecla do
atalho chegue no aplicativo_**, ou `"suppress_hotkeys": false` no
`config.json`. Desligado, o app volta a funcionar como antes — e a tecla volta
a vazar.

A lógica de reemissão tem teste próprio:

```bash
python -m artemis.hotkeys_smoketest
```

## Ícone na bandeja

O GNOME não implementa área de notificação no Shell. Quem hospeda o ícone é a
extensão **AppIndicator** (no Ubuntu, `ubuntu-appindicators@ubuntu.com`), e
sem ela ativa o ícone não aparece em lugar nenhum. O Artemis detecta isso no
boot, avisa por notificação e registra no log:

```
WARNING artemis: Sem area de notificacao na sessao; o icone nao vai aparecer.
```

Para conferir se o serviço está no ar:

```bash
busctl --user list | grep StatusNotifierWatcher
```

Sem resposta, a extensão não está ativa. `gnome-extensions enable
ubuntu-appindicators@ubuntu.com` seguido de logout/login costuma resolver. O
app continua utilizável sem bandeja: os atalhos funcionam, o indicador
flutuante aparece, e as configurações abrem pelo menu de aplicativos.

## Problemas comuns

| Sintoma | Causa provável |
| --- | --- |
| "não consegui ler nenhum teclado" | Fora do grupo `input`, ou entrou nele sem refazer o login. |
| A tecla do atalho ainda digita | Supressão desligada, ou o grab falhou — procure `Capturando com exclusividade` no `artemis.log`. |
| Grava mas não cola | Sem campo de texto em foco. O texto está no clipboard e em *Últimos ditados*. |
| Sem ícone na bandeja | Extensão AppIndicator inativa (acima). |
| Nada acontece ao apertar o atalho | Outro Artemis já está rodando: `pgrep -af "m artemis"`. |

O log fica em `~/.config/ArtemisDictation/artemis.log`.
