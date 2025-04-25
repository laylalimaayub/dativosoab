
import logging
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Estados da conversa
ESCOLHA_NATUREZA = 1

# Configurações
TELEGRAM_TOKEN = "INSIRA_SEU_TOKEN_AQUI"
PLANILHA_NOME = "Lista_Advogados"
TEMPO_ESPERA = 600  # 10 minutos

# Google Sheets Setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credenciais.json", scope)
cliente = gspread.authorize(creds)
planilha = cliente.open(PLANILHA_NOME)

# Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Início da solicitação
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    teclado = [[KeyboardButton("Cível")], [KeyboardButton("Criminal")], [KeyboardButton("Tribunal do Júri")]]
    reply_markup = ReplyKeyboardMarkup(teclado, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Qual a natureza da audiência?", reply_markup=reply_markup)
    return ESCOLHA_NATUREZA

# Após escolha da natureza
async def escolher_natureza(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    natureza = update.message.text.strip()
    context.user_data["natureza"] = natureza

    aba_nome = {
        "cível": "Civel",
        "criminal": "Criminal",
        "tribunal do júri": "Juri"
    }.get(natureza.lower())

    if not aba_nome:
        await update.message.reply_text("Natureza inválida. Por favor, escolha uma das opções fornecidas.")
        return ESCOLHA_NATUREZA

    try:
        aba = planilha.worksheet(aba_nome)
    except Exception as e:
        await update.message.reply_text(f"Erro ao acessar a aba '{aba_nome}' na planilha: {e}")
        return ConversationHandler.END

    await update.message.reply_text(f"Natureza informada: {natureza}. Procurando advogado disponível...")
    linhas = aba.get_all_records()

    for i, advogado in enumerate(linhas):
        if advogado["Status"].lower() == "livre":
            telegram_id = advogado["Telegram_ID"]
            nome = advogado["Nome"]
            mensagem = f"{nome}, você aceita a nomeação para uma audiência de natureza *{natureza}*? Responda com 'sim' ou 'não'."
            await context.bot.send_message(chat_id=telegram_id, text=mensagem, parse_mode="Markdown")
            
            context.chat_data["aguardando_resposta"] = {
                "index": i,
                "user_id": telegram_id,
                "solicitante_chat_id": update.message.chat_id,
                "aba_nome": aba_nome
            }

            await asyncio.sleep(TEMPO_ESPERA)

            if "aguardando_resposta" in context.chat_data:
                await context.bot.send_message(chat_id=telegram_id, text="Tempo esgotado. Nomeação recusada.")
                aba.update_cell(i + 2, 5, "Livre")
                continue
            return ConversationHandler.END

    await update.message.reply_text("Nenhum advogado disponível no momento.")
    return ConversationHandler.END

# Lida com respostas dos advogados
async def tratar_resposta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    resposta = update.message.text.strip().lower()
    dados = context.chat_data.get("aguardando_resposta")
    if not dados or str(update.message.chat_id) != str(dados["user_id"]):
        return

    index = dados["index"]
    solicitante_id = dados["solicitante_chat_id"]
    aba = planilha.worksheet(dados["aba_nome"])

    if resposta == "sim":
        aba.update_cell(index + 2, 4, datetime.now().strftime("%Y-%m-%d"))
        aba.update_cell(index + 2, 5, "Ocupado")
        await context.bot.send_message(chat_id=solicitante_id, text="Um advogado aceitou a nomeação.")
        await update.message.reply_text("Nomeação confirmada. Obrigado.")
        context.chat_data.pop("aguardando_resposta", None)

    elif resposta == "não":
        aba.update_cell(index + 2, 5, "Livre")
        await update.message.reply_text("Entendido. A nomeação será passada ao próximo advogado.")
        context.chat_data.pop("aguardando_resposta", None)

# Cancela o processo
async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Solicitação cancelada.")
    return ConversationHandler.END

# Main
def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conversa = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ESCOLHA_NATUREZA: [MessageHandler(filters.TEXT & ~filters.COMMAND, escolher_natureza)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    application.add_handler(conversa)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tratar_resposta))
    application.run_polling()

if __name__ == "__main__":
    main()
