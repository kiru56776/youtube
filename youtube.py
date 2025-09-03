import os
import telebot
from pytube import Search
from pytube.exceptions import VideoUnavailable, PytubeError
import tempfile
import threading
import logging
import json
from telebot import types

# --- Setup and Configuration ---

# Set up logging to get more detailed information about what the bot is doing
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# It's crucial to use environment variables for sensitive data like API tokens.
# When you deploy to Render, you will set this token in the environment variables.
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not found. Please set it before running the bot.")

bot = telebot.TeleBot(BOT_TOKEN)

# --- Helper Functions ---

def download_audio_and_send(chat_id, video_url, message_id):
    """
    Handles the entire process of downloading and sending the audio for a specific video.
    This function is run in a separate thread to prevent the main bot loop from blocking.
    """
    processing_message = None
    temp_filepath = None
    try:
        # Send a "typing" action and a message to the user to indicate processing
        bot.send_chat_action(chat_id, 'typing')
        processing_message = bot.edit_message_text("Getting audio for your selected song...", chat_id, message_id)

        # Get the video object from the URL
        video = Search(video_url).results[0]
        logger.info(f"Downloading audio for: {video.title} ({video.watch_url})")

        # Get the audio stream with the highest bitrate
        audio_stream = video.streams.filter(only_audio=True).order_by('bitrate').desc().first()
        
        if not audio_stream:
            bot.edit_message_text("Sorry, no audio streams found for this video.", chat_id, processing_message.message_id)
            logger.warning(f"No audio streams found for video: {video.title}")
            return

        # Use a temporary file to save the audio
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
            temp_filepath = temp_file.name
        
        logger.info(f"Starting download of audio to {temp_filepath}")
        audio_stream.download(output_path=os.path.dirname(temp_filepath), filename=os.path.basename(temp_filepath))
        logger.info("Download completed.")

        # Send the audio file to the user
        with open(temp_filepath, 'rb') as audio_file:
            bot.send_audio(chat_id, audio_file)
            
        bot.delete_message(chat_id, processing_message.message_id)
        
    except (PytubeError, VideoUnavailable) as e:
        error_message = f"YouTube error occurred: {e}"
        logger.error(error_message)
        bot.edit_message_text(f"Sorry, a YouTube-related error occurred while processing your request: {e}", chat_id, message_id)
            
    except Exception as e:
        error_message = f"An unexpected error occurred: {e}"
        logger.error(error_message)
        bot.edit_message_text("An unexpected error occurred while processing your request. The developer has been notified.", chat_id, message_id)
            
    finally:
        # Clean up the temporary file
        if temp_filepath and os.path.exists(temp_filepath):
            os.remove(temp_filepath)
            logger.info(f"Deleted temporary file: {temp_filepath}")

# --- Bot Command Handers ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Handles the /start and /help commands."""
    help_text = (
        "Hello! I am a YouTube Music Bot.\n"
        "Just send me the name of a song or artist, and I'll give you a list of results to choose from."
    )
    bot.reply_to(message, help_text)

# --- Main Message Handler ---

@bot.message_handler(content_types=['text'])
def handle_text_message(message):
    """Handles all text messages and presents search results as buttons."""
    query = message.text.strip()
    if len(query) > 0:
        bot.send_chat_action(message.chat.id, 'typing')
        processing_message = bot.send_message(message.chat.id, "Searching for your song on YouTube...")
        
        try:
            search_results = Search(query).results
            if not search_results:
                bot.edit_message_text("Sorry, I couldn't find any results for that query.", message.chat.id, processing_message.message_id)
                logger.warning(f"No search results found for query: {query}")
                return

            keyboard = types.InlineKeyboardMarkup()
            for i, video in enumerate(search_results[:5]):  # Show top 5 results
                # Use a dictionary to store both the URL and a new message_id
                # This is necessary because we need the message ID to edit it later
                callback_data = json.dumps({'url': video.watch_url, 'message_id': processing_message.message_id})
                keyboard.add(types.InlineKeyboardButton(f"🎧 {video.title}", callback_data=callback_data))

            bot.edit_message_text("Please choose a song:", message.chat.id, processing_message.message_id, reply_markup=keyboard)

        except Exception as e:
            logger.error(f"Error during search: {e}")
            bot.edit_message_text("An error occurred during the search. Please try again.", message.chat.id, processing_message.message_id)

# --- Callback Query Handler (for button clicks) ---

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    """Handles button clicks and initiates the download."""
    try:
        data = json.loads(call.data)
        video_url = data['url']
        message_id = data['message_id']
        
        # Respond to the callback query to remove the loading clock
        bot.answer_callback_query(call.id, text="Downloading...")
        
        # Start the download process in a new thread
        threading.Thread(target=download_audio_and_send, args=(call.message.chat.id, video_url, message_id)).start()
        
    except json.JSONDecodeError:
        logger.error(f"Invalid callback data: {call.data}")
        bot.answer_callback_query(call.id, text="Error: Invalid button data.")
    except Exception as e:
        logger.error(f"Error handling callback: {e}")
        bot.answer_callback_query(call.id, text="An unexpected error occurred.")


# --- Main Bot Loop ---

def main():
    """Starts the bot and keeps it running."""
    logger.info("Bot is starting...")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
