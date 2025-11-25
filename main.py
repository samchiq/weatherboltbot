import os
import logging
import requests
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import Application, CommandHandler, MessageHandler, InlineQueryHandler, ContextTypes, filters
from dotenv import load_dotenv
import asyncio

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
    """Получение данных о погоде через OpenWeatherMap API"""
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather"
        params = {
            'q': city,
            'appid': WEATHER_API_KEY,
            'units': 'metric',
            'lang': 'ru'
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Извлечение нужных данных
        weather_info = {
            'city': data['name'],
            'temp': data['main']['temp'],
            'description': data['weather'][0]['description'],
            'rain': data.get('rain', {}).get('1h', 0),  # Дождь за последний час
            'snow': data.get('snow', {}).get('1h', 0),  # Снег за последний час
            'clouds': data['clouds']['all'],  # Облачность в процентах
            'visibility': data.get('visibility', 10000),  # Видимость в метрах
            'wind_speed': data['wind']['speed']  # Скорость ветра м/с
        }
        
        return weather_info, None
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return None, "Город не найден. Проверьте правильность написания."
        return None, "Ошибка при получении данных о погоде."
    except requests.exceptions.RequestException:
        return None, "Не удалось связаться с сервисом погоды."
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return None, "Произошла неожиданная ошибка."


# ==================== МОДУЛЬ СООБЩЕНИЙ ====================

def generate_bolt_message(weather_data):
    """Генерация сообщения о состоянии болта на основе погоды"""
    messages = []
    
    # Проверка дождя
    if weather_data['rain'] > 0:
        messages.append("БОЛТ МОКРЫЙ - ИДЕТ ДОЖДЬ")
    else:
        messages.append("БОЛТ СУХОЙ - ДОЖДЯ НЕТ")
    
    # Проверка облачности (тень)
    if weather_data['clouds'] < 30:
        messages.append("БОЛТ ОТБРАСЫВАЕТ ТЕНЬ - ЯСНО")
    else:
        messages.append("БОЛТ НЕ ОТБРАСЫВАЕТ ТЕНЬ - ОБЛАЧНО")
    
    # Проверка тумана
    if weather_data['visibility'] < 1000:
        messages.append("БОЛТА НЕ ВИДНО - ТУМАН")
    else:
        messages.append("БОЛТ ВИДНО - ТУМАНА НЕТ")
    
    # Проверка ветра
    if weather_data['wind_speed'] > 5:
        messages.append("БОЛТ КАЧАЕТСЯ - ВЕТРЕННО")
    else:
        messages.append("БОЛТ НЕ КАЧАЕТСЯ - НЕ ВЕТРЕННО")
    
    # Проверка снега
    if weather_data['snow'] > 0:
        messages.append("БОЛТ В БЕЛОМ - СНЕГ")
    
    return "\n".join(messages)


def generate_detailed_message(weather_data):
    """Генерация детального сообщения для ЛС"""
    bolt_status = generate_bolt_message(weather_data)
    
    detailed = f"🌡 Погода в городе {weather_data['city']}\n"
    detailed += f"Температура: {weather_data['temp']:.1f}°C\n"
    detailed += f"Описание: {weather_data['description']}\n\n"
    detailed += "⚙️ Состояние метеоболта:\n"
    detailed += bolt_status
    
    return detailed


# ==================== ОБРАБОТЧИКИ БОТА ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_text = (
        "🔩 Привет! Я бот-метеоболт!\n\n"
        "Я показываю погоду через состояние волшебного болта.\n\n"
        "📍 Как пользоваться:\n"
        "• Напиши мне название города в ЛС\n"
        "• Или используй inline режим: @your_bot_name Город\n\n"
        "Попробуй написать: Москва"
    )
    await update.message.reply_text(welcome_text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений в ЛС"""
    city = update.message.text.strip()
    
    # Получение погоды
    weather_data, error = get_weather(city)
    
    if error:
        await update.message.reply_text(f"❌ {error}")
        return
    
    # Формирование и отправка ответа
    message = generate_detailed_message(weather_data)
    await update.message.reply_text(message)


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline запросов"""
    query = update.inline_query.query.strip()
    
    if not query:
        return
    
    # Получение погоды
    weather_data, error = get_weather(query)
    
    results = []
    
    if error:
        # Возврат результата с ошибкой
        results = [
            InlineQueryResultArticle(
                id="error",
                title=f"❌ {error}",
                description="Попробуйте другой город",
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ {error}"
                )
            )
        ]
    else:
        # Формирование сообщения о болте
        bolt_message = generate_bolt_message(weather_data)
        full_message = f"🔩 Метеоболт: {weather_data['city']}\n\n{bolt_message}"
        
        results = [
            InlineQueryResultArticle(
                id=weather_data['city'],
                title=f"🔩 {weather_data['city']}",
                description=f"{weather_data['temp']:.1f}°C, {weather_data['description']}",
                input_message_content=InputTextMessageContent(
                    message_text=full_message
                ),
                thumbnail_url="https://via.placeholder.com/64/4A90E2/FFFFFF?text=🔩"
            )
        ]
    
    await update.inline_query.answer(results, cache_time=300)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")


# ==================== НАСТРОЙКА БОТА ====================

def main():
    """Главная функция запуска бота"""
    # Создание приложения
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(InlineQueryHandler(inline_query))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    logger.info(f"Запуск бота на порту {PORT}")
    logger.info(f"Ожидание webhook запросов на /webhook")
    
    # Запуск webhook сервера (webhook настраивается вручную через API Telegram)
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=None,  # Отключаем автоматическую установку webhook
        drop_pending_updates=True
    )


if __name__ == '__main__':
    main()
