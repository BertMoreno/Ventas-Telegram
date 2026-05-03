import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

if not TELEGRAM_TOKEN:
    raise SystemExit("ERROR: Añade TELEGRAM_BOT_TOKEN en tu archivo .env")

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from agent import SYSTEM_PROMPT, TOOLS, run_tool
from tools import get_sales_summary

def _build_client():
    if LLM_PROVIDER == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise SystemExit("ERROR: Añade ANTHROPIC_API_KEY en .env")
        import anthropic
        return anthropic.Anthropic(api_key=api_key)

    if LLM_PROVIDER == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("ERROR: Añade OPENAI_API_KEY en .env")
        from openai import OpenAI
        return OpenAI(api_key=api_key)

    if LLM_PROVIDER == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise SystemExit("ERROR: Añade GOOGLE_API_KEY en .env")
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        # Default to gemini-1.5-flash if not specified
        model_name = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
        return genai.GenerativeModel(model_name)

    raise SystemExit("ERROR: LLM_PROVIDER debe ser anthropic | openai | gemini")

client = _build_client()

conversations: dict[int, list] = {}
user_modes: dict[int, str] = {}
user_models: dict[int, str] = {}

def _effective_model(user_id: int) -> str:
    if user_id in user_models:
        return user_models[user_id]
    if LLM_PROVIDER == "anthropic":
        return os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")
    if LLM_PROVIDER == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

def run_agent_sync(user_id: int, user_message: str) -> str:
    print(f"[DEBUG] Procesando mensaje de {user_id}: {user_message}")
    if user_id not in conversations:
        conversations[user_id] = []
    mode = user_modes.get(user_id, "coach")
    model_name = _effective_model(user_id)

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

    if LLM_PROVIDER == "anthropic":
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

    if LLM_PROVIDER == "openai":
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        )
        text = response.choices[0].message.content or ""
        messages.append({"role": "assistant", "content": text})
        return text

    # gemini
    history = []
    for m in messages[:-1]:
        role = "model" if m["role"] == "assistant" else "user"
        history.append({"role": role, "parts": [m["content"]]})
    chat_session = client.start_chat(history=history)
    resp = chat_session.send_message(f"{SYSTEM_PROMPT}\n\nUsuario: {messages[-1]['content']}")
    text = (resp.text or "").strip()
    messages.append({"role": "assistant", "content": text})
    return text

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[DEBUG] /start recibido de {update.effective_user.id}")
    user_id = update.effective_user.id
    user_modes[user_id] = "coach"
    await update.message.reply_text("Hola, soy tu Agente Manager. Estoy listo.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    print(f"[DEBUG] Mensaje recibido de {user_id}: {user_text}")
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    loop = asyncio.get_event_loop()
    try:
        response_text = await loop.run_in_executor(None, run_agent_sync, user_id, user_text)
        print(f"[DEBUG] Respuesta enviada a {user_id}")
    except Exception as e:
        print(f"[ERROR] Error procesando mensaje: {e}")
        response_text = f"Error: {e}"

    await update.message.reply_text(response_text)

def main():
    print("Bot iniciando polling...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot iniciado. Esperando mensajes...")
    app.run_polling()

if __name__ == "__main__":
    main()
