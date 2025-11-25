import os
import logging
import requests
import asyncio
from aiohttp import web
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import Application, CommandHandler, MessageHandler, InlineQueryHandler, ContextTypes, filters
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
PORT = int(os.getenv('PORT', 10000))

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== МОДУЛЬ ПОГОДЫ ====================

def get_weather(city):
    """Получение данных о погоде с поддержкой повторных попыток"""
    
    def fetch_data(query):
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            'q': query,
            'appid': WEATHER_API_KEY,
            'units': 'metric',
            'lang': 'ru'
        }
        return requests.get(url, params=params, timeout=10)

    try:
        # 1. Попытка поиска "как есть"
        response = fetch_data(city)

        # 2. Если 404 и есть дефис, пробуем заменить на пробел (Тель-Авив -> Тель Авив)
        if response.status_code == 404 and '-' in city:
            city_variant = city.replace('-', ' ')
            response = fetch_data(city_variant)

        response.raise_for_status()
        data = response.json()
        
        weather_info = {
            'city': data['name'],
            'temp': data['main']['temp'],
            'description': data['weather'][0]['description'],
            'rain': data.get('rain', {}).get('1h', 0),
            'snow': data.get('snow', {}).get('1h', 0),
            'clouds': data['clouds']['all'],
            'visibility': data.get('visibility', 10000),
            'wind_speed': data['wind']['speed']
        }
        return weather_info, None
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return None, "Город не найден. Попробуйте написать название на английском."
        return None, "Ошибка при получении данных о погоде."
    except requests.exceptions.RequestException:
        return None, "Не удалось связаться с сервисом погоды."
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return None, "Произошла неожиданная ошибка."

# ==================== МОДУЛЬ СООБЩЕНИЙ ====================

def generate_bolt_message(weather_data):
    """Генерация сообщения о состоянии болта"""
    messages = []
    if weather_data['rain'] > 0: messages.append("БОЛТ МОКРЫЙ - ИДЕТ ДОЖДЬ")
    else: messages.append("БОЛТ СУХОЙ - ДОЖДЯ НЕТ")
    
    if weather_data['clouds'] < 30: messages.append("БОЛТ ОТБРАСЫВАЕТ ТЕНЬ - ЯСНО")
    else: messages.append("БОЛТ НЕ ОТБРАСЫВАЕТ ТЕНЬ - ОБЛАЧНО")
    
    if weather_data['visibility'] < 1000: messages.append("БОЛТА НЕ ВИДНО - ТУМАН")
    else: messages.append("БОЛТ ВИДНО - ТУМАНА НЕТ")
    
    if weather_data['wind_speed'] > 5: messages.append("БОЛТ КАЧАЕТСЯ - ВЕТРЕННО")
    else: messages.append("БОЛТ НЕ КАЧАЕТСЯ - НЕ ВЕТРЕННО")
    
    if weather_data['snow'] > 0: messages.append("БОЛТ В БЕЛОМ - СНЕГ")
    
    return "\n".join(messages)

def generate_detailed_message(weather_data):
    bolt_status = generate_bolt_message(weather_data)
    return (f"🌡 Погода в городе {weather_data['city']}\n"
            f"Температура: {weather_data['temp']:.1f}°C\n"
            f"Описание: {weather_data['description']}\n\n"
            f"⚙️ Состояние метеоболта:\n{bolt_status}")

# ==================== ОБРАБОТЧИКИ БОТА ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔩 Привет! Я бот-метеоболт! Напиши мне город.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text.strip()
    weather_data, error = get_weather(city)
    if error:
        await update.message.reply_text(f"❌ {error}")
        return
    await update.message.reply_text(generate_detailed_message(weather_data))

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query: return
    
    weather_data, error = get_weather(query)
    results = []
    
    if error:
        results = [InlineQueryResultArticle(
            id="error", title=f"❌ {error}", 
            input_message_content=InputTextMessageContent(message_text=f"❌ {error}")
        )]
    else:
        bolt_message = generate_bolt_message(weather_data)
        full_message = f"🔩 Метеоболт: {weather_data['city']}\n\n{bolt_message}"
        results = [InlineQueryResultArticle(
            id=weather_data['city'],
            title=f"🔩 {weather_data['city']}",
            description=f"{weather_data['temp']:.1f}°C, {weather_data['description']}",
            input_message_content=InputTextMessageContent(message_text=full_message)
        )]
    await update.inline_query.answer(results, cache_time=300)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ==================== ВЕБ-СЕРВЕР (AIOHTTP) ====================

async def health_check_handler(request):
    """Обработчик для UptimeRobot"""
    return web.Response(text="Bot is alive!", status=200)

async def telegram_webhook_handler(request):
    """Обработчик входящих вебхуков от Telegram"""
    try:
        # Получаем бота из приложения
        bot_app = request.app['bot_app']
        # Читаем JSON
        data = await request.json()
        # Превращаем JSON в объект Update
        update = Update.de_json(data, bot_app.bot)
        # Отправляем update в очередь бота
        await bot_app.process_update(update)
        return web.Response()
    except Exception as e:
        logger.error(f"Error in webhook handler: {e}")
        return web.Response(status=500)

# ==================== ЗАПУСК ====================

async def main():
    # 1. Настройка БОТА
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(InlineQueryHandler(inline_query))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    if not WEBHOOK_URL:
        logger.critical("WEBHOOK_URL не установлен!")
        return

    # Инициализация бота
    await application.initialize()
    await application.start()
    
    # Установка вебхука (сообщаем Телеграму, куда слать данные)
    webhook_path = f"{WEBHOOK_URL}/webhook"
    logger.info(f"Setting webhook to {webhook_path}")
    await application.bot.set_webhook(url=webhook_path, drop_pending_updates=True)

    # 2. Настройка ВЕБ-СЕРВЕРА
    app = web.Application()
    app['bot_app'] = application # Сохраняем ссылку на бота внутри веб-приложения
    
    # Регистрируем маршруты
    app.router.add_get('/health', health_check_handler)   # Для UptimeRobot
    app.router.add_post('/webhook', telegram_webhook_handler) # Для Telegram

    # Запуск сервера
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    logger.info(f"Сервер запущен на порту {PORT}")
    await site.start()

    # Бесконечный цикл ожидания (чтобы программа не закрылась)
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
