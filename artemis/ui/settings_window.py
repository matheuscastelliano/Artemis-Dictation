"""Janela de configuracao (Tkinter, que ja vem com o Python).

Duas abas: Geral (chave, microfone, modelos, comportamento) e Modos (os
presets). Nada aqui e obrigatorio: tudo tambem pode ser editado direto nos
JSONs em %APPDATA%/ArtemisDictation. A janela existe para nao precisar.

Layout: o rodape com Salvar/Cancelar e empacotado ANTES do conteudo, com
side="bottom". Sem isso, o Tk encolhe o ultimo widget empacotado quando a
janela fica pequena - e o botao Salvar era o primeiro a sumir. O conteudo
das abas rola, entao a janela funciona em qualquer tamanho.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable

from .. import config as config_module
from .. import secrets_store
from ..audio import list_input_devices
from ..presets import Preset, TRIGGERS

log = logging.getLogger(__name__)

_STT_MODELS = ["gpt-transcribe", "gpt-4o-transcribe", "whisper-1"]
_TEXT_MODELS = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
_SYSTEM_DEFAULT = "(padrao do sistema)"

_HINT = "#6b6b70"
_PAD = 12
# Coluna dos rotulos + espacamentos, descontada da largura das dicas.
_LABEL_COLUMN = 165


class SettingsWindow:
    """Uma unica instancia; reabrir traz a janela existente para frente."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        on_saved: Callable[[], None],
        on_reload: Callable[[], None],
        on_open_folder: Callable[[], None],
    ):
        self._root = root
        self._on_saved = on_saved
        self._on_reload = on_reload
        self._on_open_folder = on_open_folder
        self._win: tk.Toplevel | None = None
        self._presets: list[Preset] = []
        self._selected: int | None = None
        self._suspend_select = False

    def open(self) -> None:
        if self._win is not None and self._win.winfo_exists():
            self._win.deiconify()
            self._win.lift()
            self._win.focus_force()
            return
        self._build()

    # --------------------------------------------------------- construcao

    def _build(self) -> None:
        self._config = config_module.load_config()
        self._presets = config_module.load_presets()

        win = tk.Toplevel(self._root)
        self._win = win
        win.title("Artemis Dictation - Configuracoes")
        win.geometry("780x660")
        win.minsize(560, 380)
        win.protocol("WM_DELETE_WINDOW", self._close)
        self._apply_style(win)

        # ORDEM IMPORTA: o rodape reserva seu espaco primeiro, entao ele
        # nunca e cortado quando a janela encolhe.
        footer = ttk.Frame(win, padding=(_PAD, 10))
        footer.pack(side="bottom", fill="x")
        ttk.Separator(win).pack(side="bottom", fill="x")

        ttk.Button(footer, text="Salvar", command=self._save, style="Accent.TButton").pack(
            side="right"
        )
        ttk.Button(footer, text="Cancelar", command=self._close).pack(
            side="right", padx=(0, 8)
        )

        notebook = ttk.Notebook(win)
        notebook.pack(side="top", fill="both", expand=True, padx=_PAD, pady=(_PAD, 0))
        notebook.add(self._build_general(notebook), text="  Geral  ")
        notebook.add(self._build_modes(notebook), text="  Modos  ")

        if self._presets:
            self._select_preset(0)

    def _apply_style(self, win: tk.Toplevel) -> None:
        style = ttk.Style(win)
        # Configurar a TkDefaultFont em si, e nao uma copia: os widgets ttk
        # leem a fonte nomeada, entao uma copia deixaria rotulo e campo com
        # tamanhos diferentes.
        base = tkfont.nametofont("TkDefaultFont")
        base.configure(family="Segoe UI", size=9)
        tkfont.nametofont("TkTextFont").configure(family="Segoe UI", size=9)
        self._section_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self._mono_font = tkfont.Font(family="Consolas", size=9)
        style.configure("TLabelframe.Label", font=self._section_font)
        style.configure("TLabelframe", padding=(_PAD, 8, _PAD, _PAD))
        try:
            style.configure("Accent.TButton", font=self._section_font)
        except tk.TclError:
            pass  # tema sem suporte; o botao so fica sem destaque

    # ------------------------------------------------------------ scroll

    def _scrollable(self, parent) -> ttk.Frame:
        """Area rolavel. Devolve o frame interno onde o conteudo vai."""
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(4, 8, 4, 8))

        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        def on_inner(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas(event) -> None:
            canvas.itemconfigure(window, width=event.width)  # acompanha a largura

        inner.bind("<Configure>", on_inner)
        canvas.bind("<Configure>", on_canvas)

        # A roda do mouse so rola enquanto o ponteiro esta sobre esta area.
        def wheel(event) -> None:
            canvas.yview_scroll(-int(event.delta / 120), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return inner

    def _section(self, parent, title: str) -> ttk.Labelframe:
        frame = ttk.Labelframe(parent, text=title)
        frame.pack(fill="x", expand=False, padx=8, pady=(0, 14))
        frame.columnconfigure(1, weight=1)
        return frame

    def _hint(self, parent, text: str) -> ttk.Label:
        """Texto de apoio, cinza.

        A quebra de linha acompanha a largura do container - e nao a da
        janela, porque a coluna util da aba Modos e bem menor que a da aba
        Geral por causa da lista a esquerda. Com um valor fixo, o texto
        vazava e era cortado no meio da palavra.
        """
        label = ttk.Label(
            parent, text=text, foreground=_HINT, wraplength=420, justify="left"
        )

        def refit(event, lbl=label) -> None:
            try:
                lbl.configure(wraplength=max(180, event.width - _LABEL_COLUMN))
            except tk.TclError:
                pass  # widget ja destruido

        parent.bind("<Configure>", refit, add="+")
        return label

    def _field(self, parent, row: int, label: str, widget, hint: str = "") -> int:
        """Uma linha rotulo + campo (+ dica). Devolve a proxima linha."""
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="nw", pady=(0, 4), padx=(0, 12)
        )
        widget.grid(row=row, column=1, sticky="ew", pady=(0, 4))
        row += 1
        if hint:
            self._hint(parent, hint).grid(row=row, column=1, sticky="w", pady=(0, 10))
            row += 1
        else:
            parent.grid_rowconfigure(row - 1, pad=6)
        return row

    # ------------------------------------------------------------- Geral

    def _build_general(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent)
        body = self._scrollable(page)

        # --- OpenAI ------------------------------------------------------
        openai = self._section(body, "OpenAI")
        row = 0
        self._api_key_var = tk.StringVar()
        row = self._field(
            openai,
            row,
            "API key",
            ttk.Entry(openai, textvariable=self._api_key_var, show="•"),
            f"Guardada no Gerenciador de Credenciais do Windows. "
            f"Atual: {secrets_store.masked(secrets_store.get_api_key())}. "
            "Deixe em branco para manter a que ja esta salva.",
        )
        self._stt_var = tk.StringVar(value=self._config["stt_model"])
        row = self._field(
            openai,
            row,
            "Transcricao",
            ttk.Combobox(openai, textvariable=self._stt_var, values=_STT_MODELS),
            "whisper-1 e gpt-4o-transcribe sao legados e desligam em 26/02/2027.",
        )
        self._text_model_var = tk.StringVar(value=self._config["text_model"])
        row = self._field(
            openai,
            row,
            "Texto",
            ttk.Combobox(openai, textvariable=self._text_model_var, values=_TEXT_MODELS),
            "Usado so pelos modos com pos-processamento, como o Melhorar.",
        )

        # --- Transcricao -------------------------------------------------
        audio = self._section(body, "Transcricao")
        row = 0
        try:
            names = [d["name"] for d in list_input_devices()]
        except Exception:
            names = []
        self._device_var = tk.StringVar(
            value=self._config.get("input_device") or _SYSTEM_DEFAULT
        )
        row = self._field(
            audio,
            row,
            "Microfone",
            ttk.Combobox(
                audio, textvariable=self._device_var, values=[_SYSTEM_DEFAULT] + names
            ),
        )
        self._language_var = tk.StringVar(value=self._config.get("language") or "")
        row = self._field(
            audio,
            row,
            "Idioma",
            ttk.Entry(audio, textvariable=self._language_var, width=8),
            "Codigo de duas letras: pt, en, es. Vazio deixa o modelo detectar.",
        )
        self._keywords_text = tk.Text(audio, height=6, wrap="word", font=self._mono_font)
        self._keywords_text.insert("1.0", "\n".join(self._config.get("keywords", [])))
        row = self._field(
            audio,
            row,
            "Termos",
            self._keywords_text,
            "Um por linha. Nomes que a transcricao costuma errar: clientes, "
            "produtos, jargao. Vale para todos os modos.",
        )

        # --- Comportamento -----------------------------------------------
        behavior = self._section(body, "Comportamento")
        behavior.columnconfigure(0, weight=1)

        self._beep_var = tk.BooleanVar(
            value=bool(self._config.get("sound_feedback", True))
        )
        ttk.Checkbutton(
            behavior,
            text="Beep ao iniciar e ao terminar a gravacao",
            variable=self._beep_var,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self._restore_var = tk.BooleanVar(
            value=bool(self._config.get("restore_clipboard", False))
        )
        ttk.Checkbutton(
            behavior,
            text="Devolver o clipboard anterior depois de colar",
            variable=self._restore_var,
        ).grid(row=1, column=0, sticky="w")
        self._hint(
            behavior,
            "Desligado, o ditado fica no clipboard ate voce copiar outra coisa "
            "- util quando a colagem nao encontra campo em foco.",
        ).grid(row=2, column=0, sticky="w", padx=(22, 0), pady=(0, 10))

        preview_chars = int(self._config.get("overlay_preview_chars", 120))
        self._preview_var = tk.BooleanVar(value=preview_chars > 0)
        self._preview_chars_var = tk.StringVar(value=str(preview_chars or 120))
        preview_row = ttk.Frame(behavior)
        preview_row.grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(
            preview_row,
            text="Mostrar o texto ditado no indicador",
            variable=self._preview_var,
            command=self._toggle_preview_spin,
        ).pack(side="left")
        self._preview_spin = ttk.Spinbox(
            preview_row,
            from_=40,
            to=400,
            increment=20,
            width=5,
            textvariable=self._preview_chars_var,
        )
        self._preview_spin.pack(side="left", padx=(10, 4))
        ttk.Label(preview_row, text="caracteres").pack(side="left")
        self._toggle_preview_spin()
        self._hint(
            behavior,
            "A previa serve para reconhecer o que saiu, nao para reler: o texto "
            "inteiro fica no clipboard e em 'Ultimos ditados'.",
        ).grid(row=4, column=0, sticky="w", padx=(22, 0), pady=(2, 0))

        # --- Arquivos ----------------------------------------------------
        files = self._section(body, "Arquivos de configuracao")
        files.columnconfigure(0, weight=1)
        path_entry = ttk.Entry(files)
        path_entry.insert(0, str(config_module.config_dir()))
        path_entry.configure(state="readonly")  # selecionavel, mas nao editavel
        path_entry.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(
            files, text="Abrir pasta", command=self._on_open_folder, width=16
        ).grid(row=1, column=0, sticky="w")
        ttk.Button(
            files, text="Recarregar do disco", command=self._reload_from_disk, width=20
        ).grid(row=1, column=1, sticky="w", padx=(8, 0))
        self._hint(
            files,
            "Use 'Recarregar' depois de editar config.json ou presets.json na "
            "mao. O log fica em artemis.log, na mesma pasta.",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        return page

    def _reload_from_disk(self) -> None:
        """Recarrega o app e reabre a janela com o que esta no disco."""
        self._on_reload()
        self._close()
        self._root.after(50, self.open)

    def _toggle_preview_spin(self) -> None:
        """O campo de caracteres so faz sentido com a previa ligada."""
        self._preview_spin.configure(
            state="normal" if self._preview_var.get() else "disabled"
        )

    # ------------------------------------------------------------- Modos

    def _build_modes(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent, padding=(8, 10))
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)

        # --- lista dos modos ---------------------------------------------
        left = ttk.Frame(page)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        left.rowconfigure(0, weight=1)
        self._listbox = tk.Listbox(
            left, width=18, exportselection=False, activestyle="none", borderwidth=1,
            relief="solid", highlightthickness=0,
        )
        self._listbox.grid(row=0, column=0, columnspan=2, sticky="ns")
        self._listbox.bind("<<ListboxSelect>>", self._on_list_select)
        ttk.Button(left, text="Novo", width=8, command=self._add_preset).grid(
            row=1, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Button(left, text="Remover", width=9, command=self._remove_preset).grid(
            row=1, column=1, sticky="ew", pady=(8, 0), padx=(4, 0)
        )

        # --- formulario do modo selecionado ------------------------------
        right_container = ttk.Frame(page)
        right_container.grid(row=0, column=1, sticky="nsew")
        form = ttk.Frame(self._scrollable(right_container), padding=(0, 0, 8, 0))
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        row = 0

        self._name_var = tk.StringVar()
        row = self._field(form, row, "Nome", ttk.Entry(form, textvariable=self._name_var))

        hotkey_row = ttk.Frame(form)
        hotkey_row.columnconfigure(0, weight=1)
        self._hotkey_var = tk.StringVar()
        ttk.Entry(hotkey_row, textvariable=self._hotkey_var, font=self._mono_font).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(hotkey_row, text="Capturar", width=10, command=self._capture_hotkey).grid(
            row=0, column=1, padx=(6, 0)
        )
        row = self._field(
            form,
            row,
            "Atalho",
            hotkey_row,
            "Clique em Capturar e pressione a combinacao, ou digite no formato "
            "<ctrl>+<alt>+2.",
        )

        self._trigger_var = tk.StringVar()
        row = self._field(
            form,
            row,
            "Acionamento",
            ttk.Combobox(
                form,
                textvariable=self._trigger_var,
                values=list(TRIGGERS),
                state="readonly",
                width=12,
            ),
            "toggle: aperta para gravar, aperta de novo para parar.   "
            "hold: grava enquanto voce segura - nao funciona pelo botao do "
            "Logitech, que so envia um toque.",
        )

        self._stt_prompt_text = tk.Text(form, height=5, wrap="word")
        row = self._field(
            form,
            row,
            "Contexto do STT",
            self._stt_prompt_text,
            "Como e a sua fala e de que assunto ela trata. Ajuda o modelo a "
            "acertar pontuacao e termos.",
        )

        self._refine_var = tk.BooleanVar()
        ttk.Checkbutton(
            form,
            text="Pos-processar com um LLM depois da transcricao",
            variable=self._refine_var,
            command=self._toggle_refine,
        ).grid(row=row, column=1, sticky="w", pady=(4, 2))
        row += 1
        self._hint(
            form,
            "Desligado, o modo faz uma chamada so: mais rapido, mais barato e "
            "fiel a fala. Ligue para modos que reescrevem.",
        ).grid(row=row, column=1, sticky="w", pady=(0, 10))
        row += 1

        self._preset_model_var = tk.StringVar()
        self._preset_model_combo = ttk.Combobox(
            form, textvariable=self._preset_model_var, values=[""] + _TEXT_MODELS, width=18
        )
        row = self._field(
            form,
            row,
            "Modelo do modo",
            self._preset_model_combo,
            "Vazio usa o modelo de texto global.",
        )

        self._system_prompt_text = tk.Text(form, height=8, wrap="word")
        row = self._field(
            form,
            row,
            "Instrucao do modo",
            self._system_prompt_text,
            "O que fazer com o texto transcrito. Só usada com o "
            "pos-processamento ligado.",
        )

        self._refresh_list()
        return page

    def _toggle_refine(self) -> None:
        """Sem pos-processamento, modelo e instrucao nao tem efeito."""
        state = "normal" if self._refine_var.get() else "disabled"
        self._preset_model_combo.configure(state=state)
        self._system_prompt_text.configure(
            state="normal" if self._refine_var.get() else "disabled"
        )

    # ------------------------------------------------- lista e formulario

    def _refresh_list(self) -> None:
        # Mexer na Listbox dispara <<ListboxSelect>>; sem esta trava a troca
        # de selecao se chamaria de volta no meio da atualizacao.
        self._suspend_select = True
        try:
            self._listbox.delete(0, tk.END)
            for preset in self._presets:
                self._listbox.insert(tk.END, f" {preset.name}")
        finally:
            self._suspend_select = False

    def _on_list_select(self, _event=None) -> None:
        if self._suspend_select:
            return
        selection = self._listbox.curselection()
        if selection:
            self._select_preset(selection[0])

    def _select_preset(self, index: int) -> None:
        self._commit_form()  # nao perde o que estava sendo editado
        self._refresh_list()  # o nome pode ter mudado no formulario
        self._selected = index
        preset = self._presets[index]
        self._name_var.set(preset.name)
        self._hotkey_var.set(preset.hotkey)
        self._trigger_var.set(preset.trigger)
        self._refine_var.set(preset.refine)
        self._preset_model_var.set(preset.text_model or "")
        self._set_text(self._stt_prompt_text, preset.stt_prompt)
        self._set_text(self._system_prompt_text, preset.system_prompt or "")
        self._toggle_refine()
        self._suspend_select = True
        try:
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(index)
        finally:
            self._suspend_select = False

    def _commit_form(self) -> None:
        """Copia o formulario para o preset selecionado, sem validar ainda."""
        if self._selected is None or self._selected >= len(self._presets):
            return
        preset = self._presets[self._selected]
        preset.name = self._name_var.get().strip() or preset.name
        preset.hotkey = self._hotkey_var.get().strip()
        preset.trigger = self._trigger_var.get().strip() or "toggle"
        preset.refine = bool(self._refine_var.get())
        preset.text_model = self._preset_model_var.get().strip() or None
        preset.stt_prompt = self._get_text(self._stt_prompt_text)
        preset.system_prompt = self._get_text(self._system_prompt_text) or None

    def _add_preset(self) -> None:
        self._commit_form()
        existing = {p.id for p in self._presets}
        index = 1
        while f"modo{index}" in existing:
            index += 1
        self._presets.append(
            Preset(
                id=f"modo{index}",
                name=f"Novo modo {index}",
                hotkey="",
                trigger="toggle",
                stt_prompt=self._presets[0].stt_prompt if self._presets else "",
            )
        )
        self._refresh_list()
        self._select_preset(len(self._presets) - 1)

    def _remove_preset(self) -> None:
        if self._selected is None or len(self._presets) <= 1:
            messagebox.showinfo(
                "Artemis", "Precisa sobrar pelo menos um modo.", parent=self._win
            )
            return
        name = self._presets[self._selected].name
        if not messagebox.askyesno(
            "Artemis", f"Remover o modo '{name}'?", parent=self._win
        ):
            return
        del self._presets[self._selected]
        self._selected = None
        self._refresh_list()
        self._select_preset(0)

    def _capture_hotkey(self) -> None:
        """Le a proxima combinacao digitada e converte para o formato pynput."""
        dialog = tk.Toplevel(self._win)
        dialog.title("Capturar atalho")
        dialog.transient(self._win)
        dialog.resizable(False, False)
        dialog.grab_set()
        ttk.Label(
            dialog,
            text="Pressione a combinacao desejada.",
            font=self._section_font,
            padding=(30, 22, 30, 4),
        ).pack()
        ttk.Label(dialog, text="Esc cancela.", foreground=_HINT, padding=(0, 0, 0, 22)).pack()
        dialog.update_idletasks()
        x = self._win.winfo_rootx() + (self._win.winfo_width() - dialog.winfo_width()) // 2
        y = self._win.winfo_rooty() + 160
        dialog.geometry(f"+{x}+{y}")

        def on_key(event) -> None:
            spec = _spec_from_event(event)
            if spec == "escape":
                dialog.destroy()
            elif spec:
                self._hotkey_var.set(spec)
                dialog.destroy()

        dialog.bind("<KeyPress>", on_key)
        dialog.focus_force()

    # ------------------------------------------------------------- salvar

    def _save(self) -> None:
        self._commit_form()
        try:
            validated = [Preset.from_dict(p.to_dict()) for p in self._presets]
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Artemis", str(exc), parent=self._win)
            return

        seen: dict[str, str] = {}
        for preset in validated:
            if not preset.hotkey:
                messagebox.showerror(
                    "Artemis",
                    f"O modo '{preset.name}' esta sem atalho.",
                    parent=self._win,
                )
                return
            if preset.hotkey in seen:
                messagebox.showerror(
                    "Artemis",
                    f"O atalho {preset.hotkey} esta em '{seen[preset.hotkey]}' e "
                    f"em '{preset.name}'.",
                    parent=self._win,
                )
                return
            seen[preset.hotkey] = preset.name

        device = self._device_var.get().strip()
        config = {
            **self._config,
            "input_device": None if device in ("", _SYSTEM_DEFAULT) else device,
            "stt_model": self._stt_var.get().strip() or "gpt-transcribe",
            "text_model": self._text_model_var.get().strip() or "gpt-5.6-luna",
            "language": self._language_var.get().strip() or None,
            "keywords": [
                line.strip()
                for line in self._get_text(self._keywords_text).splitlines()
                if line.strip()
            ],
            "sound_feedback": bool(self._beep_var.get()),
            "restore_clipboard": bool(self._restore_var.get()),
            "overlay_preview_chars": self._preview_chars(),
        }

        try:
            new_key = self._api_key_var.get().strip()
            if new_key:
                secrets_store.set_api_key(new_key)
            config_module.save_config(config)
            config_module.save_presets(validated)
        except Exception as exc:
            messagebox.showerror(
                "Artemis", f"Nao consegui salvar: {exc}", parent=self._win
            )
            return

        self._close()
        self._on_saved()

    def _close(self) -> None:
        win, self._win = self._win, None
        self._selected = None
        if win is not None:
            try:
                win.unbind_all("<MouseWheel>")
            except Exception:
                pass
            win.destroy()

    # ------------------------------------------------------------ helpers

    def _preview_chars(self) -> int:
        """0 quando a previa esta desligada; senao o valor do campo."""
        if not self._preview_var.get():
            return 0
        try:
            return max(20, min(400, int(self._preview_chars_var.get())))
        except ValueError:
            return 120  # campo digitado a mao com lixo: volta ao padrao

    @staticmethod
    def _get_text(widget: tk.Text) -> str:
        return widget.get("1.0", "end-1c").strip()

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        # Um Text desabilitado ignora insert em silencio; reabilita antes.
        state = str(widget.cget("state"))
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        widget.configure(state=state)


# Tk reporta os modificadores num bitmask; no Windows o Alt costuma vir em
# 0x20000, mas alguns layouts usam 0x8. Testamos os dois.
_CONTROL = 0x0004
_SHIFT = 0x0001
_ALT = 0x20008

_KEYSYM_ALIASES = {
    "space": "<space>",
    "Return": "<enter>",
    "Tab": "<tab>",
    "BackSpace": "<backspace>",
    "Insert": "<insert>",
    "Delete": "<delete>",
    "Home": "<home>",
    "End": "<end>",
    "Prior": "<page_up>",
    "Next": "<page_down>",
}

_MODIFIER_KEYSYMS = {
    "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Shift_L", "Shift_R", "Win_L", "Win_R",
}


def _spec_from_event(event) -> str:
    """Evento do Tk -> string de atalho no formato do pynput."""
    keysym = event.keysym
    if keysym == "Escape":
        return "escape"
    if keysym in _MODIFIER_KEYSYMS:
        return ""  # so um modificador: espera a tecla principal

    parts = []
    if event.state & _CONTROL:
        parts.append("<ctrl>")
    if event.state & _ALT:
        parts.append("<alt>")
    if event.state & _SHIFT:
        parts.append("<shift>")

    if keysym in _KEYSYM_ALIASES:
        parts.append(_KEYSYM_ALIASES[keysym])
    elif len(keysym) == 1:
        parts.append(keysym.lower())
    else:
        parts.append(f"<{keysym.lower()}>")  # f1..f12, teclas de midia, etc.
    return "+".join(parts)
