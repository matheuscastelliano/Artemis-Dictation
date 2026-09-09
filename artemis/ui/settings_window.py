"""Janela de configuracao (Tkinter, que ja vem com o Python).

Duas abas: Geral (chave, microfone, modelos, interface, comportamento) e
Modos (os presets). Nada aqui e obrigatorio: tudo tambem pode ser editado
direto nos JSONs em %APPDATA%/ArtemisDictation. A janela existe para nao
precisar.

Layout: o rodape com Salvar/Cancelar e empacotado ANTES do conteudo, com
side="bottom". Sem isso, o Tk encolhe o ultimo widget empacotado quando a
janela fica pequena - e o botao Salvar era o primeiro a sumir. O conteudo
das abas rola, entao a janela funciona em qualquer tamanho.

Todo texto passa por i18n.t() no momento de montar a janela. Trocar o idioma
e salvar fecha a janela; reabrir ja mostra tudo traduzido.
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable

from .. import config as config_module
from .. import secrets_store, startup
from ..audio import list_input_devices
from ..hotkeys import describe
from ..i18n import AUTO, LANGUAGE_NAMES, t
from ..presets import Preset, TRIGGERS

log = logging.getLogger(__name__)

_STT_MODELS = ["gpt-transcribe", "gpt-4o-transcribe", "whisper-1"]
_TEXT_MODELS = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]

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
        win.title(t("cfg.title"))
        win.geometry("780x680")
        win.minsize(560, 380)
        win.protocol("WM_DELETE_WINDOW", self._close)
        self._apply_style(win)

        # ORDEM IMPORTA: o rodape reserva seu espaco primeiro, entao ele
        # nunca e cortado quando a janela encolhe.
        footer = ttk.Frame(win, padding=(_PAD, 10))
        footer.pack(side="bottom", fill="x")
        ttk.Separator(win).pack(side="bottom", fill="x")
        ttk.Button(
            footer, text=t("cfg.save"), command=self._save, style="Accent.TButton"
        ).pack(side="right")
        ttk.Button(footer, text=t("cfg.cancel"), command=self._close).pack(
            side="right", padx=(0, 8)
        )

        notebook = ttk.Notebook(win)
        notebook.pack(side="top", fill="both", expand=True, padx=_PAD, pady=(_PAD, 0))
        notebook.add(self._build_general(notebook), text=t("cfg.tab.general"))
        notebook.add(self._build_modes(notebook), text=t("cfg.tab.modes"))

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

    # ------------------------------------------------------------ layout

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

        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        inner.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        # A roda do mouse so rola enquanto o ponteiro esta sobre esta area.
        def wheel(event) -> None:
            canvas.yview_scroll(-int(event.delta / 120), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return inner

    def _section(self, parent, title_key: str) -> ttk.Labelframe:
        frame = ttk.Labelframe(parent, text=t(title_key))
        frame.pack(fill="x", expand=False, padx=8, pady=(0, 14))
        frame.columnconfigure(1, weight=1)
        return frame

    def _hint(self, parent, text_value: str) -> ttk.Label:
        """Texto de apoio, cinza.

        A quebra de linha acompanha a largura do container - e nao a da
        janela, porque a coluna util da aba Modos e bem menor que a da aba
        Geral por causa da lista a esquerda. Com um valor fixo, o texto
        vazava e era cortado no meio da palavra.
        """
        label = ttk.Label(
            parent, text=text_value, foreground=_HINT, wraplength=420, justify="left"
        )

        def refit(event, lbl=label) -> None:
            try:
                lbl.configure(wraplength=max(180, event.width - _LABEL_COLUMN))
            except tk.TclError:
                pass  # widget ja destruido

        parent.bind("<Configure>", refit, add="+")
        return label

    def _field(self, parent, row: int, label_key: str, widget, hint_key: str = "") -> int:
        """Uma linha rotulo + campo (+ dica). Devolve a proxima linha."""
        ttk.Label(parent, text=t(label_key)).grid(
            row=row, column=0, sticky="nw", pady=(0, 4), padx=(0, 12)
        )
        widget.grid(row=row, column=1, sticky="ew", pady=(0, 4))
        row += 1
        if hint_key:
            self._hint(parent, t(hint_key)).grid(
                row=row, column=1, sticky="w", pady=(0, 10)
            )
            row += 1
        else:
            parent.grid_rowconfigure(row - 1, pad=6)
        return row

    def _check(self, parent, row: int, label_key: str, variable, hint_key: str = "") -> int:
        ttk.Checkbutton(parent, text=t(label_key), variable=variable).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )
        row += 1
        if hint_key:
            self._hint(parent, t(hint_key)).grid(
                row=row, column=0, columnspan=2, sticky="w", padx=(22, 0), pady=(0, 10)
            )
            row += 1
        return row

    # ------------------------------------------------------------- Geral

    def _build_general(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent)
        body = self._scrollable(page)

        # --- OpenAI ------------------------------------------------------
        openai = self._section(body, "cfg.section.openai")
        row = 0
        self._api_key_var = tk.StringVar()
        row = self._field(
            openai,
            row,
            "cfg.api_key",
            ttk.Entry(openai, textvariable=self._api_key_var, show="•"),
        )
        self._hint(
            openai,
            t("cfg.api_key.hint", current=secrets_store.masked(secrets_store.get_api_key())),
        ).grid(row=row, column=1, sticky="w", pady=(0, 10))
        row += 1
        self._stt_var = tk.StringVar(value=self._config["stt_model"])
        row = self._field(
            openai,
            row,
            "cfg.stt_model",
            ttk.Combobox(openai, textvariable=self._stt_var, values=_STT_MODELS),
            "cfg.stt_model.hint",
        )
        self._text_model_var = tk.StringVar(value=self._config["text_model"])
        row = self._field(
            openai,
            row,
            "cfg.text_model",
            ttk.Combobox(openai, textvariable=self._text_model_var, values=_TEXT_MODELS),
            "cfg.text_model.hint",
        )

        # --- Transcricao -------------------------------------------------
        audio = self._section(body, "cfg.section.transcription")
        row = 0
        try:
            names = [d["name"] for d in list_input_devices()]
        except Exception:
            names = []
        self._system_default = t("cfg.system_default")
        self._device_var = tk.StringVar(
            value=self._config.get("input_device") or self._system_default
        )
        row = self._field(
            audio,
            row,
            "cfg.microphone",
            ttk.Combobox(
                audio,
                textvariable=self._device_var,
                values=[self._system_default] + names,
            ),
        )
        self._language_var = tk.StringVar(value=self._config.get("language") or "")
        row = self._field(
            audio,
            row,
            "cfg.language",
            ttk.Entry(audio, textvariable=self._language_var, width=8),
            "cfg.language.hint",
        )
        self._keywords_text = tk.Text(audio, height=6, wrap="word", font=self._mono_font)
        self._keywords_text.insert("1.0", "\n".join(self._config.get("keywords", [])))
        row = self._field(
            audio, row, "cfg.keywords", self._keywords_text, "cfg.keywords.hint"
        )

        # --- Interface ---------------------------------------------------
        interface = self._section(body, "cfg.section.interface")
        row = 0
        self._ui_language_var = tk.StringVar(
            value=LANGUAGE_NAMES.get(self._config.get("ui_language", AUTO), "")
        )
        row = self._field(
            interface,
            row,
            "cfg.ui_language",
            ttk.Combobox(
                interface,
                textvariable=self._ui_language_var,
                values=list(LANGUAGE_NAMES.values()),
                state="readonly",
            ),
            "cfg.ui_language.hint",
        )

        self._overlay_labels = {
            "always": t("cfg.overlay.always"),
            "errors": t("cfg.overlay.errors"),
            "never": t("cfg.overlay.never"),
        }
        self._overlay_var = tk.StringVar(
            value=self._overlay_labels.get(
                self._config.get("overlay_mode", "always"),
                self._overlay_labels["always"],
            )
        )
        overlay_combo = ttk.Combobox(
            interface,
            textvariable=self._overlay_var,
            values=list(self._overlay_labels.values()),
            state="readonly",
            width=20,
        )
        overlay_combo.bind("<<ComboboxSelected>>", lambda _e: self._toggle_preview())
        row = self._field(
            interface, row, "cfg.overlay", overlay_combo, "cfg.overlay.hint"
        )

        preview_chars = int(self._config.get("overlay_preview_chars", 120))
        self._preview_var = tk.BooleanVar(value=preview_chars > 0)
        self._preview_chars_var = tk.StringVar(value=str(preview_chars or 120))
        preview_row = ttk.Frame(interface)
        preview_row.grid(row=row, column=0, columnspan=2, sticky="w")
        self._preview_check = ttk.Checkbutton(
            preview_row,
            text=t("cfg.preview"),
            variable=self._preview_var,
            command=self._toggle_preview,
        )
        self._preview_check.pack(side="left")
        self._preview_spin = ttk.Spinbox(
            preview_row,
            from_=40,
            to=400,
            increment=20,
            width=5,
            textvariable=self._preview_chars_var,
        )
        self._preview_spin.pack(side="left", padx=(10, 4))
        ttk.Label(preview_row, text=t("cfg.preview.chars")).pack(side="left")
        row += 1
        self._hint(interface, t("cfg.preview.hint")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=(22, 0), pady=(2, 0)
        )
        self._toggle_preview()

        # --- Comportamento -----------------------------------------------
        behavior = self._section(body, "cfg.section.behavior")
        behavior.columnconfigure(0, weight=1)
        row = 0
        self._beep_var = tk.BooleanVar(
            value=bool(self._config.get("sound_feedback", True))
        )
        row = self._check(behavior, row, "cfg.beep", self._beep_var)
        self._restore_var = tk.BooleanVar(
            value=bool(self._config.get("restore_clipboard", False))
        )
        row = self._check(
            behavior,
            row,
            "cfg.restore_clipboard",
            self._restore_var,
            "cfg.restore_clipboard.hint",
        )
        # So no Linux: no Windows o hook do pynput nao consegue engolir a
        # tecla, entao a caixa nao teria efeito nenhum.
        self._suppress_var = tk.BooleanVar(
            value=bool(self._config.get("suppress_hotkeys", True))
        )
        if sys.platform != "win32":
            row = self._check(
                behavior,
                row,
                "cfg.suppress",
                self._suppress_var,
                "cfg.suppress.hint",
            )

        # Estado real do registro, nao do config: se alguem apagou a entrada
        # por fora, a caixa precisa refletir o que existe de fato.
        self._autostart_var = tk.BooleanVar(value=startup.is_enabled())
        row = self._check(
            behavior, row, "cfg.autostart", self._autostart_var, "cfg.autostart.hint"
        )
        self._hint(
            behavior, t("cfg.autostart.frozen_hint", command=startup.command())
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=(22, 0))

        # --- Arquivos ----------------------------------------------------
        files = self._section(body, "cfg.section.files")
        files.columnconfigure(0, weight=1)
        path_entry = ttk.Entry(files)
        path_entry.insert(0, str(config_module.config_dir()))
        path_entry.configure(state="readonly")  # selecionavel, mas nao editavel
        path_entry.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(
            files, text=t("cfg.open_folder"), command=self._on_open_folder, width=18
        ).grid(row=1, column=0, sticky="w")
        ttk.Button(
            files, text=t("cfg.reload"), command=self._reload_from_disk, width=20
        ).grid(row=1, column=1, sticky="w", padx=(8, 0))
        self._hint(files, t("cfg.files.hint")).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        return page

    def _reload_from_disk(self) -> None:
        """Recarrega o app e reabre a janela com o que esta no disco."""
        self._on_reload()
        self._close()
        self._root.after(50, self.open)

    def _toggle_preview(self) -> None:
        """A previa so existe se o indicador aparecer em ditados normais."""
        overlay_on = self._overlay_var.get() == self._overlay_labels["always"]
        self._preview_check.configure(state="normal" if overlay_on else "disabled")
        self._preview_spin.configure(
            state="normal" if overlay_on and self._preview_var.get() else "disabled"
        )

    # ------------------------------------------------------------- Modos

    def _build_modes(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent, padding=(8, 10))
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)

        left = ttk.Frame(page)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        left.rowconfigure(0, weight=1)
        self._listbox = tk.Listbox(
            left,
            width=18,
            exportselection=False,
            activestyle="none",
            borderwidth=1,
            relief="solid",
            highlightthickness=0,
        )
        self._listbox.grid(row=0, column=0, columnspan=2, sticky="ns")
        self._listbox.bind("<<ListboxSelect>>", self._on_list_select)
        ttk.Button(left, text=t("cfg.mode.new"), width=9, command=self._add_preset).grid(
            row=1, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Button(
            left, text=t("cfg.mode.remove"), width=10, command=self._remove_preset
        ).grid(row=1, column=1, sticky="ew", pady=(8, 0), padx=(4, 0))

        right_container = ttk.Frame(page)
        right_container.grid(row=0, column=1, sticky="nsew")
        form = ttk.Frame(self._scrollable(right_container), padding=(0, 0, 8, 0))
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        row = 0

        self._name_var = tk.StringVar()
        row = self._field(
            form, row, "cfg.mode.name", ttk.Entry(form, textvariable=self._name_var)
        )

        hotkey_row = ttk.Frame(form)
        hotkey_row.columnconfigure(0, weight=1)
        self._hotkey_var = tk.StringVar()
        ttk.Entry(hotkey_row, textvariable=self._hotkey_var, font=self._mono_font).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(
            hotkey_row, text=t("cfg.mode.capture"), width=11, command=self._capture_hotkey
        ).grid(row=0, column=1, padx=(6, 0))
        row = self._field(
            form, row, "cfg.mode.hotkey", hotkey_row, "cfg.mode.hotkey.hint"
        )

        self._trigger_var = tk.StringVar()
        row = self._field(
            form,
            row,
            "cfg.mode.trigger",
            ttk.Combobox(
                form,
                textvariable=self._trigger_var,
                values=list(TRIGGERS),
                state="readonly",
                width=12,
            ),
            "cfg.mode.trigger.hint",
        )

        self._stt_prompt_text = tk.Text(form, height=5, wrap="word")
        row = self._field(
            form,
            row,
            "cfg.mode.stt_prompt",
            self._stt_prompt_text,
            "cfg.mode.stt_prompt.hint",
        )

        self._refine_var = tk.BooleanVar()
        ttk.Checkbutton(
            form,
            text=t("cfg.mode.refine"),
            variable=self._refine_var,
            command=self._toggle_refine,
        ).grid(row=row, column=1, sticky="w", pady=(4, 2))
        row += 1
        self._hint(form, t("cfg.mode.refine.hint")).grid(
            row=row, column=1, sticky="w", pady=(0, 10)
        )
        row += 1

        self._preset_model_var = tk.StringVar()
        self._preset_model_combo = ttk.Combobox(
            form,
            textvariable=self._preset_model_var,
            values=[""] + _TEXT_MODELS,
            width=18,
        )
        row = self._field(
            form,
            row,
            "cfg.mode.model",
            self._preset_model_combo,
            "cfg.mode.model.hint",
        )

        self._system_prompt_text = tk.Text(form, height=8, wrap="word")
        row = self._field(
            form,
            row,
            "cfg.mode.system_prompt",
            self._system_prompt_text,
            "cfg.mode.system_prompt.hint",
        )

        self._refresh_list()
        return page

    def _toggle_refine(self) -> None:
        """Sem pos-processamento, modelo e instrucao nao tem efeito."""
        state = "normal" if self._refine_var.get() else "disabled"
        self._preset_model_combo.configure(state=state)
        self._system_prompt_text.configure(state=state)

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
        while f"mode{index}" in existing:
            index += 1
        self._presets.append(
            Preset(
                id=f"mode{index}",
                name=t("cfg.mode.new_name", n=index),
                hotkey="",
                trigger="toggle",
                stt_prompt=self._presets[0].stt_prompt if self._presets else "",
            )
        )
        self._refresh_list()
        self._select_preset(len(self._presets) - 1)

    def _remove_preset(self) -> None:
        if self._selected is None or len(self._presets) <= 1:
            messagebox.showinfo("Artemis", t("dlg.keep_one_mode"), parent=self._win)
            return
        name = self._presets[self._selected].name
        if not messagebox.askyesno(
            "Artemis", t("dlg.remove_mode", name=name), parent=self._win
        ):
            return
        del self._presets[self._selected]
        self._selected = None
        self._refresh_list()
        self._select_preset(0)

    def _capture_hotkey(self) -> None:
        """Escuta o teclado e acumula o CONJUNTO de teclas seguradas.

        Nao fecha no primeiro <KeyPress>: continua ouvindo ate o usuario
        soltar todas as teclas, permitindo combinacoes com varias teclas
        "normais" ao mesmo tempo (ex. h+j+k), nao so modificador+1 tecla.
        """
        dialog = tk.Toplevel(self._win)
        dialog.title(t("cfg.capture.title"))
        dialog.transient(self._win)
        dialog.resizable(False, False)
        dialog.grab_set()
        ttk.Label(
            dialog,
            text=t("cfg.capture.prompt"),
            font=self._section_font,
            padding=(30, 22, 30, 4),
        ).pack()
        feedback = ttk.Label(dialog, text="", foreground=_HINT)
        feedback.pack()
        ttk.Label(
            dialog, text=t("cfg.capture.hint"), foreground=_HINT, padding=(0, 2, 0, 2)
        ).pack()
        ttk.Label(
            dialog, text=t("cfg.capture.escape"), foreground=_HINT, padding=(0, 0, 0, 22)
        ).pack()
        dialog.update_idletasks()
        x = self._win.winfo_rootx() + (self._win.winfo_width() - dialog.winfo_width()) // 2
        y = self._win.winfo_rooty() + 160
        dialog.geometry(f"+{x}+{y}")

        # `down` = teclas fisicamente seguradas agora; `seen` = uniao de tudo
        # que passou por `down` durante a captura (vira a spec final).
        down: set[str] = set()
        seen: set[str] = set()
        pending_release: dict[str, object] = {}
        state = {"pending_finish": None, "closed": False}

        def finish(spec: str | None) -> None:
            if state["closed"]:
                return
            state["closed"] = True
            if spec:
                self._hotkey_var.set(spec)
            dialog.destroy()

        def refresh_feedback() -> None:
            if not seen:
                feedback.configure(text="")
                return
            spec = _spec_from_keys(seen)
            mark = "" if down else "  ✓"
            feedback.configure(text=f"{describe(spec)}{mark}")

        def schedule_finish() -> None:
            token = object()
            state["pending_finish"] = token

            def do_finish() -> None:
                if state["pending_finish"] is token:
                    finish(_spec_from_keys(seen))

            dialog.after(150, do_finish)

        def on_press(event) -> None:
            keysym = event.keysym
            if keysym == "Escape":
                finish(None)
                return
            state["pending_finish"] = None
            pending_release.pop(keysym, None)  # KeyPress novo = era autorepeat
            if keysym not in down:
                down.add(keysym)
                seen.add(keysym)
                refresh_feedback()

        def on_release(event) -> None:
            keysym = event.keysym
            if keysym == "Escape" or keysym not in down:
                return
            token = object()
            pending_release[keysym] = token

            def confirm_release() -> None:
                if pending_release.get(keysym) is not token:
                    return  # um KeyPress chegou antes: era autorepeat, ignora
                pending_release.pop(keysym, None)
                down.discard(keysym)
                refresh_feedback()
                if down:
                    return
                # So Ctrl/Alt/Shift sozinhos nao fecham a captura (evita
                # atalho global acidental nessas teclas, usadas o tempo
                # todo). Super/cmd sozinho fecha: e' assim que varias
                # teclas "especiais" de teclado (Fn, busca, etc.) chegam,
                # sem tecla companheira nenhuma.
                has_normal = any(k not in _MODIFIER_KEYSYMS for k in seen)
                has_cmd = any(_MODIFIER_TOKEN.get(k) == "cmd" for k in seen)
                if has_normal or has_cmd:
                    schedule_finish()
                else:
                    seen.clear()  # so modificador(es) foram soltos: tenta de novo
                    refresh_feedback()

            dialog.after(1, confirm_release)

        def on_focus_out(event) -> None:
            # Perdeu foco com tecla(s) presas (alt-tab etc.): zera em vez de
            # travar esperando um release que nunca vai chegar aqui.
            down.clear()
            seen.clear()
            pending_release.clear()
            state["pending_finish"] = None
            refresh_feedback()

        dialog.bind("<KeyPress>", on_press)
        dialog.bind("<KeyRelease>", on_release)
        dialog.bind("<FocusOut>", on_focus_out)
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(None))
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
                    t("dlg.mode_no_hotkey", name=preset.name),
                    parent=self._win,
                )
                return
            if preset.hotkey in seen:
                messagebox.showerror(
                    "Artemis",
                    t(
                        "dlg.hotkey_taken",
                        spec=preset.hotkey,
                        first=seen[preset.hotkey],
                        second=preset.name,
                    ),
                    parent=self._win,
                )
                return
            seen[preset.hotkey] = preset.name

        device = self._device_var.get().strip()
        config = {
            **self._config,
            "input_device": None if device in ("", self._system_default) else device,
            "stt_model": self._stt_var.get().strip() or "gpt-transcribe",
            "text_model": self._text_model_var.get().strip() or "gpt-5.6-luna",
            "language": self._language_var.get().strip() or None,
            "keywords": [
                line.strip()
                for line in self._get_text(self._keywords_text).splitlines()
                if line.strip()
            ],
            "ui_language": self._selected_language(),
            "overlay_mode": self._selected_overlay_mode(),
            "overlay_preview_chars": self._preview_chars(),
            "sound_feedback": bool(self._beep_var.get()),
            "restore_clipboard": bool(self._restore_var.get()),
            "suppress_hotkeys": bool(self._suppress_var.get()),
            "start_with_windows": bool(self._autostart_var.get()),
        }

        try:
            new_key = self._api_key_var.get().strip()
            if new_key:
                secrets_store.set_api_key(new_key)
            config_module.save_config(config)
            config_module.save_presets(validated)
        except Exception as exc:
            messagebox.showerror(
                "Artemis", t("dlg.save_failed", error=exc), parent=self._win
            )
            return

        self._close()
        self._on_saved()  # aplica idioma, atalhos e inicializacao automatica

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

    def _selected_language(self) -> str:
        """Nome exibido -> codigo do idioma."""
        chosen = self._ui_language_var.get()
        for code, name in LANGUAGE_NAMES.items():
            if name == chosen:
                return code
        return AUTO

    def _selected_overlay_mode(self) -> str:
        chosen = self._overlay_var.get()
        for mode, label in self._overlay_labels.items():
            if label == chosen:
                return mode
        return "always"

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

# Teclas de midia (XF86...) do X11 -> mesmo nome de token usado em
# hotkeys_evdev.py (_NAMED). O nome do keysym precisa bater literalmente
# com a chave usada la; e' o contrato entre os dois arquivos.
_XF86_ALIASES = {
    "XF86AudioPlay": "<media_playpause>",
    "XF86AudioPause": "<media_playpause>",
    "XF86AudioStop": "<media_stop>",
    "XF86AudioNext": "<media_next>",
    "XF86AudioPrev": "<media_prev>",
    "XF86AudioMute": "<media_mute>",
    "XF86AudioRaiseVolume": "<media_volume_up>",
    "XF86AudioLowerVolume": "<media_volume_down>",
    "XF86MonBrightnessUp": "<media_brightness_up>",
    "XF86MonBrightnessDown": "<media_brightness_down>",
    "XF86WLAN": "<media_wifi>",
    "XF86RFKill": "<media_airplane>",
}

_MODIFIER_KEYSYMS = {
    "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Shift_L", "Shift_R", "Win_L", "Win_R",
    # No X11/Tk a tecla Super/Windows chega como "Super_L"/"Super_R" (Win_L/
    # Win_R praticamente nunca aparece na pratica no Linux); Meta_L/Meta_R
    # aparecem em alguns layouts/teclados no lugar de Alt ou Super.
    "Super_L", "Super_R", "Meta_L", "Meta_R",
}

_MODIFIER_TOKEN = {
    "Control_L": "ctrl", "Control_R": "ctrl",
    "Alt_L": "alt", "Alt_R": "alt",
    "Shift_L": "shift", "Shift_R": "shift",
    "Win_L": "cmd", "Win_R": "cmd",
    "Super_L": "cmd", "Super_R": "cmd",
    "Meta_L": "cmd", "Meta_R": "cmd",
}
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "cmd")


def _spec_from_keys(keys: set[str]) -> str:
    """Conjunto de keysyms segurados durante a captura -> spec de atalho.

    Substitui o antigo _spec_from_event (que lia so um evento por vez, via
    bitmask de event.state): aqui os modificadores tambem vem do conjunto
    de keysyms vistos, entao qualquer numero de teclas "normais" seguradas
    ao mesmo tempo (ex. h+j+k) e' representado sem depender de um unico
    evento carregar tudo.
    """
    mods = {_MODIFIER_TOKEN[k] for k in keys if k in _MODIFIER_TOKEN}
    others = []
    for keysym in keys:
        if keysym in _MODIFIER_TOKEN:
            continue
        if keysym in _KEYSYM_ALIASES:
            others.append(_KEYSYM_ALIASES[keysym])
        elif keysym in _XF86_ALIASES:
            others.append(_XF86_ALIASES[keysym])
        elif len(keysym) == 1:
            others.append(keysym.lower())
        else:
            others.append(f"<{keysym.lower()}>")  # f1..f12, teclas desconhecidas, etc.

    parts = [f"<{m}>" for m in _MODIFIER_ORDER if m in mods]
    parts.extend(sorted(others))  # ordem deterministica p/ teclas normais
    return "+".join(parts)
