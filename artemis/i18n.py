"""Traducao da interface: portugues, ingles e espanhol.

Um dicionario plano por idioma, com chaves pontuadas. `t()` resolve na hora
da chamada, entao trocar o idioma nas configuracoes e recarregar ja muda
tudo - nao ha string capturada no momento do import.

Faltando uma chave, cai para o ingles; faltando no ingles tambem, devolve a
propria chave. Uma traducao incompleta deixa a tela feia, nunca quebra o app.

Para adicionar um idioma: copie o bloco "en", traduza os valores e registre
o codigo em LANGUAGE_NAMES.
"""

from __future__ import annotations

import ctypes
import logging

log = logging.getLogger(__name__)

DEFAULT = "en"
AUTO = "auto"

# Cada idioma aparece com o proprio nome: quem procura "Espanol" nao esta
# lendo a interface em portugues.
LANGUAGE_NAMES = {
    AUTO: "Automatico / Automatic",
    "pt": "Portugues (Brasil)",
    "en": "English",
    "es": "Espanol",
}

# LANGID primario do Windows -> nosso codigo.
_WINDOWS_PRIMARY = {0x16: "pt", 0x09: "en", 0x0A: "es"}

_current = DEFAULT


def detect() -> str:
    """Idioma da interface do Windows, ou o padrao se nao for suportado."""
    try:
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return _WINDOWS_PRIMARY.get(langid & 0x3FF, DEFAULT)
    except Exception:
        return DEFAULT


def set_language(code: str | None) -> str:
    """Define o idioma corrente. 'auto' segue o Windows. Devolve o efetivo."""
    global _current
    if not code or code == AUTO:
        _current = detect()
    elif code in _TRANSLATIONS:
        _current = code
    else:
        log.warning("Idioma '%s' desconhecido; usando '%s'.", code, DEFAULT)
        _current = DEFAULT
    return _current


def current() -> str:
    return _current


def t(key: str, **kwargs) -> str:
    """Texto traduzido. kwargs preenchem os campos {} da string."""
    text = _TRANSLATIONS.get(_current, {}).get(key)
    if text is None:
        text = _TRANSLATIONS[DEFAULT].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text  # traducao com placeholder errado nao derruba a tela
    return text


_TRANSLATIONS: dict[str, dict[str, str]] = {}

# --------------------------------------------------------------- English

_TRANSLATIONS["en"] = {
    # -- linha de comando
    'cli.set_key.prompt': 'Paste your OpenAI API key (it will not be shown) and press Enter.',
    'cli.set_key.cancel': 'An empty Enter cancels.',
    'cli.set_key.label': 'API key: ',
    'cli.set_key.cancelled': 'Cancelled, nothing was changed.',
    'cli.set_key.saved': 'Saved to the Credential Manager: {masked}',
    'cli.already_running': 'Artemis Dictation is already running (check the tray icon).',
    'cli.default_device': '  <- default',
    # -- estados e notificacoes
    "status.ready": "Ready",
    "status.recording": "Recording...",
    "status.processing": "Processing...",
    "status.done": "Done",
    "status.error": "Error",
    "status.recording_with": "Recording... ({mode})",
    "status.processing_with": "Processing... ({mode})",
    "status.too_short": "Recording too short, ignored.",
    "status.cancelled": "Recording cancelled.",
    "status.clipboard_only": "Text on the clipboard",
    "status.clipboard_only.detail": "Could not paste automatically: press Ctrl+V.",
    "status.copied": "Copied",
    "status.copied.detail": "Paste it with Ctrl+V.",
    # -- bandeja
    "tray.tooltip": "Artemis Dictation",
    "tray.recent": "Recent dictations",
    "tray.recent.empty": "(none yet)",
    "tray.recent.clear": "Clear",
    "tray.settings": "Settings...",
    "tray.quit": "Quit",
    "tray.notify.no_key": "Set your OpenAI API key to get started.",
    # -- erros
    "err.no_api_key": "OpenAI API key is not set.",
    "err.no_api_key.detail": "Open the Artemis settings from the tray icon.",
    "err.no_api_key.cli": "Open the Artemis settings, or set OPENAI_API_KEY.",
    "err.invalid_api_key": "OpenAI API key is invalid or revoked.",
    "err.invalid_api_key.detail": "Check the key in the Artemis settings.",
    "err.no_model_access": "Your account cannot access this model.",
    "err.rate_limit": "OpenAI usage limit reached. Try again shortly.",
    "err.timeout": "OpenAI took too long to answer.",
    "err.timeout.detail": "Very long dictation, or a slow connection.",
    "err.offline": "No connection to OpenAI.",
    "err.offline.detail": "Check your internet.",
    "err.api_status": "OpenAI returned error {status}.",
    "err.unexpected_audio": "Unexpected failure while processing the audio.",
    "err.unexpected": "Unexpected failure.",
    "err.empty_transcription": "I did not catch anything in the audio.",
    "err.empty_transcription.detail": "The transcript came back empty. Speak closer to the microphone.",
    "err.mic_busy": "Microphone unavailable or in use by another app.",
    "err.mic_open": "Could not open the microphone.",
    "err.mic_list": "Could not list the audio devices.",
    "err.recording_stop": "Could not finish the recording.",
    "err.clipboard": "Could not copy the text to the clipboard.",
    "err.paste": "Could not paste into the active application.",
    "err.paste.detail": "The text is on the clipboard: press Ctrl+V. ({error})",
    "err.hotkey_invalid": "Invalid shortcut: '{spec}'.",
    "err.hotkey_invalid.detail": "Use the pynput format, e.g. <ctrl>+<alt>+<space> or <ctrl>+<alt>+1.",
    "err.hotkey_empty": "Empty shortcut for '{mode}'.",
    "err.hotkey_conflict": "The shortcut '{spec}' is in two modes ('{first}' and '{second}').",
    "err.hotkey_problems": "Shortcut problems",
    "err.config_read": "Could not read {file}. Fix it or delete the file.",
    "err.config_object": "config.json should contain a JSON object.",
    "err.presets_list": "presets.json should contain a non-empty list.",
    "err.preset_invalid": "Invalid preset in presets.json.",
    "err.keyring_save": "Could not save the API key to Credential Manager.",
    "err.startup_write": "Could not change the Windows startup entry.",
    # -- janela de configuracao
    "cfg.title": "Artemis Dictation - Settings",
    "cfg.tab.general": "  General  ",
    "cfg.tab.modes": "  Modes  ",
    "cfg.save": "Save",
    "cfg.cancel": "Cancel",
    "cfg.section.openai": "OpenAI",
    "cfg.section.transcription": "Transcription",
    "cfg.section.behavior": "Behaviour",
    "cfg.section.files": "Configuration files",
    "cfg.section.interface": "Interface",
    "cfg.api_key": "API key",
    "cfg.api_key.hint": "Stored in the Windows Credential Manager. Current: {current}. Leave blank to keep the one already saved.",
    "cfg.api_key.none": "(none)",
    "cfg.stt_model": "Transcription",
    "cfg.stt_model.hint": "whisper-1 and gpt-4o-transcribe are legacy and shut down on 2027-02-26.",
    "cfg.text_model": "Text",
    "cfg.text_model.hint": "Used only by modes with post-processing, such as Improve.",
    "cfg.microphone": "Microphone",
    "cfg.system_default": "(system default)",
    "cfg.language": "Speech language",
    "cfg.language.hint": "Two-letter code: pt, en, es. Empty lets the model detect it.",
    "cfg.keywords": "Vocabulary",
    "cfg.keywords.hint": "One per line. Names the transcription tends to get wrong: clients, products, jargon. Applies to every mode.",
    "cfg.ui_language": "Interface language",
    "cfg.ui_language.hint": "Changes menus, settings and messages. 'Automatic' follows Windows.",
    "cfg.beep": "Beep when recording starts and stops",
    "cfg.restore_clipboard": "Restore the previous clipboard after pasting",
    "cfg.restore_clipboard.hint": "Off, the dictation stays on the clipboard until you copy something else - handy when the paste finds no focused field.",
    "cfg.overlay": "On-screen indicator",
    "cfg.overlay.always": "Always show",
    "cfg.overlay.errors": "Only on errors",
    "cfg.overlay.never": "Never show",
    "cfg.overlay.hint": "The floating indicator in the bottom-right corner. The tray icon still changes colour either way.",
    "cfg.preview": "Show the dictated text in the indicator",
    "cfg.preview.chars": "characters",
    "cfg.preview.hint": "The preview is there to recognise what came out, not to re-read it: the full text is on the clipboard and under 'Recent dictations'.",
    "cfg.autostart": "Start Artemis when Windows starts",
    "cfg.autostart.hint": "Adds an entry under the current user only - no administrator rights needed.",
    "cfg.autostart.frozen_hint": "Registered command: {command}",
    "cfg.open_folder": "Open folder",
    "cfg.reload": "Reload from disk",
    "cfg.files.hint": "Use 'Reload' after editing config.json or presets.json by hand. The log is in artemis.log, in the same folder.",
    # -- aba de modos
    "cfg.mode.new": "New",
    "cfg.mode.remove": "Remove",
    "cfg.mode.new_name": "New mode {n}",
    "cfg.mode.name": "Name",
    "cfg.mode.hotkey": "Shortcut",
    "cfg.mode.capture": "Capture",
    "cfg.mode.hotkey.hint": "Click Capture and press the combination, or type it as <ctrl>+<alt>+2.",
    "cfg.mode.trigger": "Trigger",
    "cfg.mode.trigger.hint": "toggle: press to record, press again to stop.   hold: records while you hold it - does not work with a Logitech button, which only sends a tap.",
    "cfg.mode.stt_prompt": "STT context",
    "cfg.mode.stt_prompt.hint": "What your speech is like and what it is about. Helps the model get punctuation and terms right.",
    "cfg.mode.refine": "Post-process with an LLM after transcription",
    "cfg.mode.refine.hint": "Off, the mode makes a single call: faster, cheaper and faithful to your speech. Turn it on for modes that rewrite.",
    "cfg.mode.model": "Mode model",
    "cfg.mode.model.hint": "Empty uses the global text model.",
    "cfg.mode.system_prompt": "Mode instruction",
    "cfg.mode.system_prompt.hint": "What to do with the transcribed text. Only used with post-processing on.",
    "cfg.capture.title": "Capture shortcut",
    "cfg.capture.prompt": "Press the combination you want.",
    "cfg.capture.escape": "Esc cancels.",
    # -- dialogos
    "dlg.keep_one_mode": "At least one mode must remain.",
    "dlg.remove_mode": "Remove the mode '{name}'?",
    "dlg.mode_no_hotkey": "The mode '{name}' has no shortcut.",
    "dlg.hotkey_taken": "The shortcut {spec} is used by '{first}' and by '{second}'.",
    "dlg.save_failed": "Could not save: {error}",
    # -- presets padrao
    "preset.transcribe.name": "Transcribe",
    "preset.transcribe.description": "Faithful to your speech. Punctuation and obvious fixes only.",
    "preset.improve.name": "Improve",
    "preset.improve.description": "Transcribes and cleans the text up without changing the tone.",
    "preset.stt_prompt": (
        "Dictation, informal and colloquial register, with software "
        "development and product management jargon mixed in. Transcribe "
        "exactly what was said, preserving slang, swearing and the speaker's "
        "voice. Add punctuation and paragraph breaks where they help. Do not "
        "rewrite, do not summarise, do not make it formal."
    ),
    "preset.improve.system_prompt": (
        "You receive a transcript of speech and return the same content "
        "written better.\n\n"
        "Do: fix grammar and transcription errors; remove repetition, "
        "hesitation and filler; improve clarity and sentence structure; "
        "organise into paragraphs.\n\n"
        "Do not: invent anything that was not said; change the tone (informal "
        "stays informal); make it formal; add a greeting, a sign-off or a "
        "comment of your own; explain what you did.\n\n"
        "Reply with the final text only, no quotes and no preamble."
    ),
}

# ------------------------------------------------------------- Portugues

_TRANSLATIONS["pt"] = {
    'cli.set_key.prompt': 'Cole a API key da OpenAI (nao aparece na tela) e tecle Enter.',
    'cli.set_key.cancel': 'Enter vazio cancela.',
    'cli.set_key.label': 'API key: ',
    'cli.set_key.cancelled': 'Cancelado, nada foi alterado.',
    'cli.set_key.saved': 'Salva no Gerenciador de Credenciais: {masked}',
    'cli.already_running': 'O Artemis Dictation ja esta rodando (veja o icone na bandeja).',
    'cli.default_device': '  <- padrao',
    "status.ready": "Pronto",
    "status.recording": "Gravando...",
    "status.processing": "Processando...",
    "status.done": "Pronto",
    "status.error": "Erro",
    "status.recording_with": "Gravando... ({mode})",
    "status.processing_with": "Processando... ({mode})",
    "status.too_short": "Gravacao curta demais, ignorada.",
    "status.cancelled": "Gravacao cancelada.",
    "status.clipboard_only": "Texto no clipboard",
    "status.clipboard_only.detail": "Nao consegui colar automaticamente: use Ctrl+V.",
    "status.copied": "Copiado",
    "status.copied.detail": "Cole com Ctrl+V.",
    "tray.tooltip": "Artemis Dictation",
    "tray.recent": "Ultimos ditados",
    "tray.recent.empty": "(nenhum ainda)",
    "tray.recent.clear": "Limpar",
    "tray.settings": "Configuracoes...",
    "tray.quit": "Sair",
    "tray.notify.no_key": "Configure sua API key da OpenAI para comecar.",
    "err.no_api_key": "API key da OpenAI nao configurada.",
    "err.no_api_key.detail": "Abra as configuracoes do Artemis pelo icone na bandeja.",
    "err.no_api_key.cli": "Abra as configuracoes do Artemis ou defina OPENAI_API_KEY.",
    "err.invalid_api_key": "API key da OpenAI invalida ou revogada.",
    "err.invalid_api_key.detail": "Confira a chave nas configuracoes do Artemis.",
    "err.no_model_access": "Sua conta nao tem acesso a este modelo.",
    "err.rate_limit": "Limite de uso da OpenAI atingido. Tente de novo em instantes.",
    "err.timeout": "A OpenAI demorou demais para responder.",
    "err.timeout.detail": "Ditado muito longo ou conexao lenta.",
    "err.offline": "Sem conexao com a OpenAI.",
    "err.offline.detail": "Verifique sua internet.",
    "err.api_status": "A OpenAI retornou erro {status}.",
    "err.unexpected_audio": "Falha inesperada ao processar o audio.",
    "err.unexpected": "Falha inesperada.",
    "err.empty_transcription": "Nao entendi nada no audio.",
    "err.empty_transcription.detail": "A transcricao voltou vazia. Fale mais perto do microfone.",
    "err.mic_busy": "Microfone indisponivel ou em uso por outro aplicativo.",
    "err.mic_open": "Nao consegui abrir o microfone.",
    "err.mic_list": "Nao consegui listar os dispositivos de audio.",
    "err.recording_stop": "Falha ao encerrar a gravacao.",
    "err.clipboard": "Nao consegui copiar o texto para a area de transferencia.",
    "err.paste": "Nao consegui colar na aplicacao ativa.",
    "err.paste.detail": "O texto esta no clipboard: use Ctrl+V. ({error})",
    "err.hotkey_invalid": "Atalho invalido: '{spec}'.",
    "err.hotkey_invalid.detail": "Use o formato do pynput, ex: <ctrl>+<alt>+<space> ou <ctrl>+<alt>+1.",
    "err.hotkey_empty": "Atalho vazio para '{mode}'.",
    "err.hotkey_conflict": "O atalho '{spec}' esta em dois modos ('{first}' e '{second}').",
    "err.hotkey_problems": "Atalhos com problema",
    "err.config_read": "Nao consegui ler {file}. Corrija ou apague o arquivo.",
    "err.config_object": "config.json deveria conter um objeto JSON.",
    "err.presets_list": "presets.json deveria conter uma lista nao vazia.",
    "err.preset_invalid": "Preset invalido em presets.json.",
    "err.keyring_save": "Nao consegui salvar a API key no Gerenciador de Credenciais.",
    "err.startup_write": "Nao consegui alterar a inicializacao com o Windows.",
    "cfg.title": "Artemis Dictation - Configuracoes",
    "cfg.tab.general": "  Geral  ",
    "cfg.tab.modes": "  Modos  ",
    "cfg.save": "Salvar",
    "cfg.cancel": "Cancelar",
    "cfg.section.openai": "OpenAI",
    "cfg.section.transcription": "Transcricao",
    "cfg.section.behavior": "Comportamento",
    "cfg.section.files": "Arquivos de configuracao",
    "cfg.section.interface": "Interface",
    "cfg.api_key": "API key",
    "cfg.api_key.hint": "Guardada no Gerenciador de Credenciais do Windows. Atual: {current}. Deixe em branco para manter a que ja esta salva.",
    "cfg.api_key.none": "(nenhuma)",
    "cfg.stt_model": "Transcricao",
    "cfg.stt_model.hint": "whisper-1 e gpt-4o-transcribe sao legados e desligam em 26/02/2027.",
    "cfg.text_model": "Texto",
    "cfg.text_model.hint": "Usado so pelos modos com pos-processamento, como o Melhorar.",
    "cfg.microphone": "Microfone",
    "cfg.system_default": "(padrao do sistema)",
    "cfg.language": "Idioma da fala",
    "cfg.language.hint": "Codigo de duas letras: pt, en, es. Vazio deixa o modelo detectar.",
    "cfg.keywords": "Termos",
    "cfg.keywords.hint": "Um por linha. Nomes que a transcricao costuma errar: clientes, produtos, jargao. Vale para todos os modos.",
    "cfg.ui_language": "Idioma da interface",
    "cfg.ui_language.hint": "Muda menus, configuracoes e mensagens. 'Automatico' segue o Windows.",
    "cfg.beep": "Beep ao iniciar e ao terminar a gravacao",
    "cfg.restore_clipboard": "Devolver o clipboard anterior depois de colar",
    "cfg.restore_clipboard.hint": "Desligado, o ditado fica no clipboard ate voce copiar outra coisa - util quando a colagem nao encontra campo em foco.",
    "cfg.overlay": "Indicador na tela",
    "cfg.overlay.always": "Sempre mostrar",
    "cfg.overlay.errors": "So em erros",
    "cfg.overlay.never": "Nunca mostrar",
    "cfg.overlay.hint": "O indicador flutuante no canto inferior direito. De qualquer forma, o icone da bandeja continua mudando de cor.",
    "cfg.preview": "Mostrar o texto ditado no indicador",
    "cfg.preview.chars": "caracteres",
    "cfg.preview.hint": "A previa serve para reconhecer o que saiu, nao para reler: o texto inteiro fica no clipboard e em 'Ultimos ditados'.",
    "cfg.autostart": "Iniciar o Artemis junto com o Windows",
    "cfg.autostart.hint": "Cria uma entrada so para o seu usuario - nao precisa de administrador.",
    "cfg.autostart.frozen_hint": "Comando registrado: {command}",
    "cfg.open_folder": "Abrir pasta",
    "cfg.reload": "Recarregar do disco",
    "cfg.files.hint": "Use 'Recarregar' depois de editar config.json ou presets.json na mao. O log fica em artemis.log, na mesma pasta.",
    "cfg.mode.new": "Novo",
    "cfg.mode.remove": "Remover",
    "cfg.mode.new_name": "Novo modo {n}",
    "cfg.mode.name": "Nome",
    "cfg.mode.hotkey": "Atalho",
    "cfg.mode.capture": "Capturar",
    "cfg.mode.hotkey.hint": "Clique em Capturar e pressione a combinacao, ou digite no formato <ctrl>+<alt>+2.",
    "cfg.mode.trigger": "Acionamento",
    "cfg.mode.trigger.hint": "toggle: aperta para gravar, aperta de novo para parar.   hold: grava enquanto voce segura - nao funciona pelo botao do Logitech, que so envia um toque.",
    "cfg.mode.stt_prompt": "Contexto do STT",
    "cfg.mode.stt_prompt.hint": "Como e a sua fala e de que assunto ela trata. Ajuda o modelo a acertar pontuacao e termos.",
    "cfg.mode.refine": "Pos-processar com um LLM depois da transcricao",
    "cfg.mode.refine.hint": "Desligado, o modo faz uma chamada so: mais rapido, mais barato e fiel a fala. Ligue para modos que reescrevem.",
    "cfg.mode.model": "Modelo do modo",
    "cfg.mode.model.hint": "Vazio usa o modelo de texto global.",
    "cfg.mode.system_prompt": "Instrucao do modo",
    "cfg.mode.system_prompt.hint": "O que fazer com o texto transcrito. So usada com o pos-processamento ligado.",
    "cfg.capture.title": "Capturar atalho",
    "cfg.capture.prompt": "Pressione a combinacao desejada.",
    "cfg.capture.escape": "Esc cancela.",
    "dlg.keep_one_mode": "Precisa sobrar pelo menos um modo.",
    "dlg.remove_mode": "Remover o modo '{name}'?",
    "dlg.mode_no_hotkey": "O modo '{name}' esta sem atalho.",
    "dlg.hotkey_taken": "O atalho {spec} esta em '{first}' e em '{second}'.",
    "dlg.save_failed": "Nao consegui salvar: {error}",
    "preset.transcribe.name": "Transcrever",
    "preset.transcribe.description": "Fiel a fala. So pontuacao e correcoes obvias.",
    "preset.improve.name": "Melhorar",
    "preset.improve.description": "Transcreve e limpa o texto sem mudar o tom.",
    "preset.stt_prompt": (
        "Ditado em portugues brasileiro, registro informal e coloquial, com "
        "termos tecnicos de desenvolvimento de software e gestao de produto em "
        "ingles no meio das frases. Transcreva exatamente o que foi dito, "
        "preservando giria, palavrao e o jeito de falar da pessoa. Adicione "
        "pontuacao e quebras de paragrafo onde fizer sentido. Nao reescreva, "
        "nao resuma e nao formalize."
    ),
    "preset.improve.system_prompt": (
        "Voce recebe a transcricao de uma fala em portugues brasileiro e "
        "devolve o mesmo conteudo com melhor qualidade de escrita.\n\n"
        "Faca: corrigir erros de gramatica e de transcricao; remover "
        "repeticoes, hesitacoes e vicios de linguagem ('tipo', 'ne', 'entao "
        "assim'); melhorar a clareza e a estrutura das frases; organizar em "
        "paragrafos.\n\n"
        "Nao faca: inventar informacao que nao estava na fala; mudar o tom "
        "(se estava informal, continua informal); formalizar; adicionar "
        "saudacao, despedida ou comentario seu; explicar o que voce fez.\n\n"
        "Responda apenas com o texto final, sem aspas e sem preambulo."
    ),
}

# --------------------------------------------------------------- Espanol

_TRANSLATIONS["es"] = {
    'cli.set_key.prompt': 'Pega tu API key de OpenAI (no se mostrara) y pulsa Enter.',
    'cli.set_key.cancel': 'Un Enter vacio cancela.',
    'cli.set_key.label': 'API key: ',
    'cli.set_key.cancelled': 'Cancelado, no se cambio nada.',
    'cli.set_key.saved': 'Guardada en el Administrador de Credenciales: {masked}',
    'cli.already_running': 'Artemis Dictation ya esta ejecutandose (mira el icono de la bandeja).',
    'cli.default_device': '  <- predeterminado',
    "status.ready": "Listo",
    "status.recording": "Grabando...",
    "status.processing": "Procesando...",
    "status.done": "Listo",
    "status.error": "Error",
    "status.recording_with": "Grabando... ({mode})",
    "status.processing_with": "Procesando... ({mode})",
    "status.too_short": "Grabacion demasiado corta, ignorada.",
    "status.cancelled": "Grabacion cancelada.",
    "status.clipboard_only": "Texto en el portapapeles",
    "status.clipboard_only.detail": "No pude pegar automaticamente: usa Ctrl+V.",
    "status.copied": "Copiado",
    "status.copied.detail": "Pegalo con Ctrl+V.",
    "tray.tooltip": "Artemis Dictation",
    "tray.recent": "Ultimos dictados",
    "tray.recent.empty": "(ninguno todavia)",
    "tray.recent.clear": "Limpiar",
    "tray.settings": "Configuracion...",
    "tray.quit": "Salir",
    "tray.notify.no_key": "Configura tu API key de OpenAI para empezar.",
    "err.no_api_key": "La API key de OpenAI no esta configurada.",
    "err.no_api_key.detail": "Abre la configuracion de Artemis desde el icono de la bandeja.",
    "err.no_api_key.cli": "Abre la configuracion de Artemis o define OPENAI_API_KEY.",
    "err.invalid_api_key": "API key de OpenAI invalida o revocada.",
    "err.invalid_api_key.detail": "Revisa la clave en la configuracion de Artemis.",
    "err.no_model_access": "Tu cuenta no tiene acceso a este modelo.",
    "err.rate_limit": "Limite de uso de OpenAI alcanzado. Intenta de nuevo en un momento.",
    "err.timeout": "OpenAI tardo demasiado en responder.",
    "err.timeout.detail": "Dictado muy largo o conexion lenta.",
    "err.offline": "Sin conexion con OpenAI.",
    "err.offline.detail": "Revisa tu internet.",
    "err.api_status": "OpenAI devolvio el error {status}.",
    "err.unexpected_audio": "Fallo inesperado al procesar el audio.",
    "err.unexpected": "Fallo inesperado.",
    "err.empty_transcription": "No entendi nada en el audio.",
    "err.empty_transcription.detail": "La transcripcion volvio vacia. Habla mas cerca del microfono.",
    "err.mic_busy": "Microfono no disponible o en uso por otra aplicacion.",
    "err.mic_open": "No pude abrir el microfono.",
    "err.mic_list": "No pude listar los dispositivos de audio.",
    "err.recording_stop": "No pude terminar la grabacion.",
    "err.clipboard": "No pude copiar el texto al portapapeles.",
    "err.paste": "No pude pegar en la aplicacion activa.",
    "err.paste.detail": "El texto esta en el portapapeles: usa Ctrl+V. ({error})",
    "err.hotkey_invalid": "Atajo invalido: '{spec}'.",
    "err.hotkey_invalid.detail": "Usa el formato de pynput, por ejemplo <ctrl>+<alt>+<space> o <ctrl>+<alt>+1.",
    "err.hotkey_empty": "Atajo vacio para '{mode}'.",
    "err.hotkey_conflict": "El atajo '{spec}' esta en dos modos ('{first}' y '{second}').",
    "err.hotkey_problems": "Atajos con problemas",
    "err.config_read": "No pude leer {file}. Corrigelo o borra el archivo.",
    "err.config_object": "config.json deberia contener un objeto JSON.",
    "err.presets_list": "presets.json deberia contener una lista no vacia.",
    "err.preset_invalid": "Preset invalido en presets.json.",
    "err.keyring_save": "No pude guardar la API key en el Administrador de Credenciales.",
    "err.startup_write": "No pude cambiar el inicio automatico con Windows.",
    "cfg.title": "Artemis Dictation - Configuracion",
    "cfg.tab.general": "  General  ",
    "cfg.tab.modes": "  Modos  ",
    "cfg.save": "Guardar",
    "cfg.cancel": "Cancelar",
    "cfg.section.openai": "OpenAI",
    "cfg.section.transcription": "Transcripcion",
    "cfg.section.behavior": "Comportamiento",
    "cfg.section.files": "Archivos de configuracion",
    "cfg.section.interface": "Interfaz",
    "cfg.api_key": "API key",
    "cfg.api_key.hint": "Guardada en el Administrador de Credenciales de Windows. Actual: {current}. Dejalo en blanco para mantener la que ya esta guardada.",
    "cfg.api_key.none": "(ninguna)",
    "cfg.stt_model": "Transcripcion",
    "cfg.stt_model.hint": "whisper-1 y gpt-4o-transcribe son heredados y se apagan el 26/02/2027.",
    "cfg.text_model": "Texto",
    "cfg.text_model.hint": "Usado solo por los modos con posprocesamiento, como Mejorar.",
    "cfg.microphone": "Microfono",
    "cfg.system_default": "(predeterminado del sistema)",
    "cfg.language": "Idioma del habla",
    "cfg.language.hint": "Codigo de dos letras: pt, en, es. Vacio deja que el modelo lo detecte.",
    "cfg.keywords": "Terminos",
    "cfg.keywords.hint": "Uno por linea. Nombres que la transcripcion suele equivocar: clientes, productos, jerga. Vale para todos los modos.",
    "cfg.ui_language": "Idioma de la interfaz",
    "cfg.ui_language.hint": "Cambia menus, configuracion y mensajes. 'Automatico' sigue a Windows.",
    "cfg.beep": "Pitido al iniciar y terminar la grabacion",
    "cfg.restore_clipboard": "Devolver el portapapeles anterior despues de pegar",
    "cfg.restore_clipboard.hint": "Apagado, el dictado se queda en el portapapeles hasta que copies otra cosa - util cuando el pegado no encuentra un campo enfocado.",
    "cfg.overlay": "Indicador en pantalla",
    "cfg.overlay.always": "Mostrar siempre",
    "cfg.overlay.errors": "Solo en errores",
    "cfg.overlay.never": "No mostrar nunca",
    "cfg.overlay.hint": "El indicador flotante en la esquina inferior derecha. De cualquier forma, el icono de la bandeja sigue cambiando de color.",
    "cfg.preview": "Mostrar el texto dictado en el indicador",
    "cfg.preview.chars": "caracteres",
    "cfg.preview.hint": "La vista previa sirve para reconocer lo que salio, no para releerlo: el texto completo esta en el portapapeles y en 'Ultimos dictados'.",
    "cfg.autostart": "Iniciar Artemis junto con Windows",
    "cfg.autostart.hint": "Crea una entrada solo para tu usuario - no requiere administrador.",
    "cfg.autostart.frozen_hint": "Comando registrado: {command}",
    "cfg.open_folder": "Abrir carpeta",
    "cfg.reload": "Recargar del disco",
    "cfg.files.hint": "Usa 'Recargar' despues de editar config.json o presets.json a mano. El registro esta en artemis.log, en la misma carpeta.",
    "cfg.mode.new": "Nuevo",
    "cfg.mode.remove": "Quitar",
    "cfg.mode.new_name": "Modo nuevo {n}",
    "cfg.mode.name": "Nombre",
    "cfg.mode.hotkey": "Atajo",
    "cfg.mode.capture": "Capturar",
    "cfg.mode.hotkey.hint": "Haz clic en Capturar y pulsa la combinacion, o escribela como <ctrl>+<alt>+2.",
    "cfg.mode.trigger": "Activacion",
    "cfg.mode.trigger.hint": "toggle: pulsa para grabar, pulsa otra vez para parar.   hold: graba mientras lo mantienes - no funciona con el boton Logitech, que solo envia un toque.",
    "cfg.mode.stt_prompt": "Contexto del STT",
    "cfg.mode.stt_prompt.hint": "Como es tu habla y de que trata. Ayuda al modelo a acertar la puntuacion y los terminos.",
    "cfg.mode.refine": "Posprocesar con un LLM despues de la transcripcion",
    "cfg.mode.refine.hint": "Apagado, el modo hace una sola llamada: mas rapido, mas barato y fiel a tu habla. Enciendelo para modos que reescriben.",
    "cfg.mode.model": "Modelo del modo",
    "cfg.mode.model.hint": "Vacio usa el modelo de texto global.",
    "cfg.mode.system_prompt": "Instruccion del modo",
    "cfg.mode.system_prompt.hint": "Que hacer con el texto transcrito. Solo se usa con el posprocesamiento encendido.",
    "cfg.capture.title": "Capturar atajo",
    "cfg.capture.prompt": "Pulsa la combinacion que quieras.",
    "cfg.capture.escape": "Esc cancela.",
    "dlg.keep_one_mode": "Tiene que quedar al menos un modo.",
    "dlg.remove_mode": "Quitar el modo '{name}'?",
    "dlg.mode_no_hotkey": "El modo '{name}' no tiene atajo.",
    "dlg.hotkey_taken": "El atajo {spec} esta en '{first}' y en '{second}'.",
    "dlg.save_failed": "No pude guardar: {error}",
    "preset.transcribe.name": "Transcribir",
    "preset.transcribe.description": "Fiel a tu habla. Solo puntuacion y correcciones obvias.",
    "preset.improve.name": "Mejorar",
    "preset.improve.description": "Transcribe y limpia el texto sin cambiar el tono.",
    "preset.stt_prompt": (
        "Dictado en espanol, registro informal y coloquial, con terminos "
        "tecnicos de desarrollo de software y gestion de producto en ingles "
        "entre las frases. Transcribe exactamente lo que se dijo, preservando "
        "la jerga, las palabrotas y la forma de hablar de la persona. Agrega "
        "puntuacion y saltos de parrafo donde tenga sentido. No reescribas, "
        "no resumas y no lo formalices."
    ),
    "preset.improve.system_prompt": (
        "Recibes la transcripcion de un habla en espanol y devuelves el mismo "
        "contenido mejor escrito.\n\n"
        "Haz: corregir errores de gramatica y de transcripcion; quitar "
        "repeticiones, vacilaciones y muletillas; mejorar la claridad y la "
        "estructura de las frases; organizar en parrafos.\n\n"
        "No hagas: inventar informacion que no estaba; cambiar el tono (si era "
        "informal, sigue informal); formalizar; agregar saludo, despedida o un "
        "comentario tuyo; explicar lo que hiciste.\n\n"
        "Responde solo con el texto final, sin comillas y sin preambulo."
    ),
}
