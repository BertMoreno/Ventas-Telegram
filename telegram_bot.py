import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_TOKEN:
    raise SystemExit("ERROR: Añade TELEGRAM_BOT_TOKEN en tu archivo .env")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

from agent import SYSTEM_PROMPT, TOOLS, run_tool
from tools import get_sales_summary

# --- Configuración de Modelos ---
MODEL_OPTIONS = {
    "gemini": {
        "Gemini 3 Flash": "models/gemini-3-flash-preview",
        "Gemini 3.1 Pro (Low)": "models/gemini-3.1-pro-preview",
        "Gemini 3.1 Pro (High)": "models/gemini-3.1-pro-preview-customtools",
    },
    "anthropic": {
        "Opus 4.7": "claude-4-7-opus",
        "Sonnet 4.6": "claude-4-6-sonnet",
        "Haiku 4.5": "claude-4-5-haiku",
    },
    "openai": {
        "ChatGPT 5.3": "chatgpt-5.3",
        "Thinking 5.5": "thinking-5.5",
        "GPT-OOS Medium": "gpt-oos-medium",
    }
}

# Clientes globales (se inicializan si hay API KEY)
clients = {}

def _init_clients():
    # Gemini
    gemini_key = os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        clients["gemini"] = genai
    
    # Anthropic
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        import anthropic
        clients["anthropic"] = anthropic.Anthropic(api_key=anthropic_key)
        
    # OpenAI
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        from openai import OpenAI
        clients["openai"] = OpenAI(api_key=openai_key)

_init_clients()

# Estado de los usuarios
conversations: dict[int, list] = {}
user_modes: dict[int, str] = {}
user_providers: dict[int, str] = {}
user_models: dict[int, str] = {}

def _get_user_config(user_id: int):
    provider = user_providers.get(user_id, "gemini")
    default_model = list(MODEL_OPTIONS[provider].values())[0]
    model = user_models.get(user_id, default_model)
    return provider, model

def run_agent_sync(user_id: int, user_message: str) -> str:
    print(f"[DEBUG] Procesando mensaje de {user_id}: {user_message}")
    if user_id not in conversations:
        conversations[user_id] = []
    
    mode = user_modes.get(user_id, "coach")
    provider, model_name = _get_user_config(user_id)
    
    messages = conversations[user_id]
    if mode == "sales":
        sales_context = get_sales_summary()
        prompt = (
            "Modo seleccionado: análisis de datos de ventas.\n"
            f"DATOS DE VENTAS:\n{sales_context}\n\n"
            f"PREGUNTA DEL USUARIO:\n{user_message}"
        )
        messages.append({"role": "user", "content": prompt})
    else:
        messages.append({"role": "user", "content": user_message})

    try:
        if provider == "anthropic":
            client = clients.get("anthropic")
            if not client: return "Error: Anthropic no configurado (falta API KEY)."
            response = client.messages.create(
                model=model_name,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            text_parts = [block.text for block in response.content if block.type == "text"]
            result = "\n".join(text_parts)
            messages.append({"role": "assistant", "content": result})
            return result

        if provider == "openai":
            client = clients.get("openai")
            if not client: return "Error: OpenAI no configurado (falta API KEY)."
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            )
            text = response.choices[0].message.content or ""
            messages.append({"role": "assistant", "content": text})
            return text

        # gemini
        if "gemini" not in clients: return "Error: Gemini no configurado (falta API KEY)."
        model = clients["gemini"].GenerativeModel(model_name)
        history = []
        for m in messages[:-1]:
            role = "model" if m["role"] == "assistant" else "user"
            history.append({"role": role, "parts": [m["content"]]})
        chat_session = model.start_chat(history=history)
        resp = chat_session.send_message(f"{SYSTEM_PROMPT}\n\nUsuario: {messages[-1]['content']}")
        text = (resp.text or "").strip()
        messages.append({"role": "assistant", "content": text})
        return text
    except Exception as e:
        return f"❌ Error con el modelo {model_name}: {e}"

# --- Handlers de Telegram ---

def get_main_keyboard():
    # Teclado persistente en la parte inferior
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⚙️ Configurar IA"), KeyboardButton("📊 Análisis Ventas")]],
        resize_keyboard=True
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_modes[user_id] = "coach"
    await update.message.reply_text(
        "👋 ¡Hola! Soy tu Agente Manager de Vanguardia.\n\n"
        "He activado un menú inferior para que puedas cambiar de IA en cualquier momento.",
        reply_markup=get_main_keyboard()
    )
    await cmd_config(update, context)

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💎 Gemini", callback_query_data="prov_gemini")],
        [InlineKeyboardButton("❄️ Anthropic", callback_query_data="prov_anthropic")],
        [InlineKeyboardButton("🧠 OpenAI", callback_query_data="prov_openai")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "¿Qué proveedor quieres usar?"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data.startswith("prov_"):
        provider = data.split("_")[1]
        user_providers[user_id] = provider
        # Mostrar modelos del proveedor
        keyboard = []
        for name, model_id in MODEL_OPTIONS[provider].items():
            keyboard.append([InlineKeyboardButton(name, callback_query_data=f"mod_{provider}_{name}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"Has elegido {provider.capitalize()}. Ahora elige el modelo de vanguardia:", reply_markup=reply_markup)

    elif data.startswith("mod_"):
        parts = data.split("_")
        provider = parts[1]
        model_name = parts[2]
        model_id = MODEL_OPTIONS[provider][model_name]
        
        user_providers[user_id] = provider
        user_models[user_id] = model_id
        
        await query.edit_message_text(f"✅ *Configuración Aplicada*\n\n🧠 IA: {provider.capitalize()}\n🤖 Modelo: {model_name}\n\nYa puedes escribirme.", parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    
    # Manejar botones del teclado principal
    if user_text == "⚙️ Configurar IA":
        await cmd_config(update, context)
        return
    if user_text == "📊 Análisis Ventas":
        user_modes[user_id] = "sales"
        await update.message.reply_text("Modo análisis de ventas activado. ¿Qué quieres saber?")
        return

    # Configuración por defecto si no existe
    if user_id not in user_providers:
        user_providers[user_id] = "gemini"
    if user_id not in user_models:
        user_models[user_id] = "models/gemini-3-flash-preview"

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    loop = asyncio.get_event_loop()
    try:
        response_text = await loop.run_in_executor(None, run_agent_sync, user_id, user_text)
    except Exception as e:
        response_text = f"❌ Error crítico: {e}"

    await update.message.reply_text(response_text, reply_markup=get_main_keyboard())

def main():
    print("Bot iniciando (Versión con Menú Persistente)...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot en funcionamiento. Esperando mensajes...")
    app.run_polling()

if __name__ == "__main__":
    main()
