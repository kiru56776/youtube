import os
import telebot
from pytube import Search
from pytube.exceptions import VideoUnavailable, PytubeError
import tempfile
import threading
import logging

# --- Setup and Configuration ---

# Set up logging to get more detailed information about what the bot is doing
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# It's crucial to use environment variables for sensitive data like API tokens.
# When you deploy to Render, you will set this token in the environment variables.
# For local testing, you can uncomment the line below and replace 'YOUR_BOT_TOKEN' with your actual token.
# os.environ['BOT_TOKEN'] = 'YOUR_BOT_TOKEN' 

BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not found. Please set it before running the bot.")

bot = telebot.TeleBot(BOT_TOKEN)

# --- Helper Functions ---

def download_audio_and_send(chat_id, query):
    """
    Handles the entire process of searching, downloading, and sending the audio.
    This function is run in a separate thread to prevent the main bot loop from blocking.
    """
    logger.info(f"User {chat_id} requested audio for: {query}")
    processing_message = None
    temp_filepath = None
    try:
        # Send a "typing" action and a message to the user to indicate processing
        bot.send_chat_action(chat_id, 'typing')
        processing_message = bot.send_message(chat_id, "Searching for your song on YouTube...")

        # Search for the video
        search_results = Search(query).results
        
        if not search_results:
            bot.edit_message_text("Sorry, I couldn't find any results for that query.", chat_id, processing_message.message_id)
            logger.warning(f"No search results found for query: {query}")
            return

        video = search_results[0]
        logger.info(f"Found video: {video.title} ({video.watch_url})")
        
        # Update the processing message with the video title
        bot.edit_message_text(f"Found it! Getting audio for: *{video.title}*.", chat_id, processing_message.message_id, parse_mode='Markdown')
        
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
        if processing_message:
            bot.edit_message_text(f"Sorry, a YouTube-related error occurred while processing your request: {e}", chat_id, processing_message.message_id)
        else:
            bot.send_message(chat_id, f"Sorry, a YouTube-related error occurred while processing your request: {e}")
            
    except Exception as e:
        error_message = f"An unexpected error occurred: {e}"
        logger.error(error_message)
        if processing_message:
            bot.edit_message_text("An unexpected error occurred while processing your request. The developer has been notified.", chat_id, processing_message.message_id)
        else:
            bot.send_message(chat_id, "An unexpected error occurred while processing your request. The developer has been notified.")
            
    finally:
        # Clean up the temporary file
        if temp_filepath and os.path.exists(temp_filepath):
            os.remove(temp_filepath)
            logger.info(f"Deleted temporary file: {temp_filepath}")

# --- Bot Command Handlers ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Handles the /start and /help commands."""
    help_text = (
        "Hello! I am a YouTube Music Bot.\n"
        "Just send me the name of a song or artist, and I'll send you the audio.\n\n"
        "Example: *Rema Calm Down*\n\n"
        "Note: I'll search for the top result on YouTube and download the highest quality audio stream."
    )
    bot.reply_to(message, help_text, parse_mode='Markdown')

# --- Main Message Handler ---

@bot.message_handler(content_types=['text'])
def handle_text_message(message):
    """Handles all text messages and initiates the audio download process."""
    if len(message.text.strip()) > 0:
        # Start the download process in a new thread
        threading.Thread(target=download_audio_and_send, args=(message.chat.id, message.text)).start()

# --- Main Bot Loop ---

def main():
    """Starts the bot and keeps it running."""
    logger.info("Bot is starting...")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
