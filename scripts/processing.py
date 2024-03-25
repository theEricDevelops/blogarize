# Standard library imports
import os
import shutil
import logging
from typing import Tuple

# Third-party imports for web and file handling
import requests
from flask import session
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage

# Third-party imports for video and audio processing
from pytube import YouTube
from moviepy.editor import *
import speech_recognition as sr
import mutagen

# Third-party imports for AI and environment variables
from openai import OpenAI
from dotenv import load_dotenv

# Third-party imports for text processing
import markdown as md
from bs4 import BeautifulSoup

# Local imports
from app import app

logging.basicConfig()
fh = logging.FileHandler(f'logs/blogarize.log', mode='w')
fh.setLevel(logging.DEBUG)  # Set the handler's level to DEBUG
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(lineno)d - %(funcName)s - %(message)s')
fh.setFormatter(formatter)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)  # Set the logger's level to DEBUG
logger.addHandler(fh)
logging.debug("processing.py: And away we go!")

load_dotenv()

def get_youtube_video(link: str) -> Tuple[YouTube,  str]:
    logging.info(f"We'll create an instance of the YouTube class to get some info.")
    yt = YouTube(link, on_progress_callback=on_yt_progress)
    filename = secure_filename(f"{yt.title}.mp4")
    logging.info(f"Complete filename is {filename}")
    return yt, filename

def download_youtube_video(
        yt: YouTube, 
        filename: str, 
        upload_folder: str
        ) -> str:
    try:
        logging.info(f"Attempting to download the video: {yt.title} ({upload_folder}/{filename})")
        yt.streams.filter(only_audio=True, subtype="mp4").order_by('abr').last().download(output_path=upload_folder, filename=filename)
        logging.info(f"Downloaded {filename}")
        return filename
    except Exception as e:
        logging.error(f"An error occurred in 'download_youtube_video' (processing.py): {e}")
        return str(e)
    
def on_yt_progress(stream, chunks, bytes_remaining):
    total_size = stream.filesize
    bytes_downloaded = total_size - bytes_remaining
    percentage_of_completion = (bytes_downloaded / total_size) * 100
    print(f"Downloaded {percentage_of_completion}%")

def save_uploaded_file(
        file: FileStorage, 
        upload_folder: str,
        mp4_size: int
        ) -> str:
    logging.info(f"Attempting to save uploaded file: {file} to {upload_folder}")
    try:
        filename = secure_filename(file.filename)
        filepath = os.path.join(upload_folder, filename)
        logging.info(f"Filepath is {filepath}")
        # If file with the same name exists and the uploaded file is a different size, overwrite it
        if os.path.exists(filepath):
            existing_file_size = os.path.getsize(filepath)
            
            # Log the sizes of the existing and uploaded files
            logging.info(f"Existing file size: {existing_file_size}")
            logging.info(f"Uploaded file size: {mp4_size}")
            
            # If uploaded file is a different size, overwrite existing file
            if mp4_size != existing_file_size:
                logging.info(f"Uploaded file is a different size. Overwriting existing file: {filepath}")
                file.stream.seek(0)  # Reset stream position to beginning of file
                shutil.copyfileobj(file.stream, open(filepath, 'wb'))

                # Delete .wav, .txt, and .md files
                base_filename, _ = os.path.splitext(filename)

                # Log the files to be deleted
                logging.info(f"Files to be deleted: {base_filename}.wav, {base_filename}.txt, {base_filename}.md")
                
                for ext in ['.wav', '.txt', '.md', '.png']:
                    file_to_delete = os.path.join(upload_folder, base_filename + ext)
                    if os.path.exists(file_to_delete):
                        os.remove(file_to_delete)
                        logging.info(f"Deleted file: {file_to_delete}")
        else:
            file.save(filepath)

        session['progress'] = app.config.get('steps')['Downloaded']
        session['completed_step'] = 'File saved. Moving on to audio conversion.'
        # Check if the MP4 file has a title
        mp4_file = mutagen.File(filepath, easy=True)
        title = mp4_file.get('title')
        if title:
            logging.info(f"Title of the uploaded file: {title[0]}")
        else:
            # If the file doesn't have a title, use the filename (without the extension) as the title
            title = os.path.splitext(filename)[0]
            title = title.replace('_', ' ').title()
            logging.info(f"File doesn't have a title. Using filename as title: {title}")

        return title, filename
    except Exception as e:
        return str(e)

def convert_video_to_audio(
        video_filepath :str = None, 
        audio_filepath :str = None
        ) -> str:
    
    if not os.path.exists(audio_filepath):
        logging.info(f"Attempting to convert {video_filepath} to {audio_filepath}")
        try:
            videoclip = VideoFileClip(video_filepath)
            audioclip = videoclip.audio
            audioclip.write_audiofile(filename=audio_filepath, codec='pcm_s32le')
            audioclip.close()
            videoclip.close()
            logging.info(f"Audio file saved as {audioclip.filename}")
            return audioclip.filename
        except Exception as e:
            try:
                logging.info(f"The file {video_filepath} is not a valid video file. Audio only?")
                audioclip = AudioFileClip(video_filepath)
                audioclip.write_audiofile(filename=audio_filepath, codec='pcm_s32le')
                audioclip.close()
                logging.info(f"Audio file saved as {audioclip.filename}")
                session['progress'] = app.config.get('steps')['ConvertedAudio']
                session['completed_step'] = 'Audio file created. Moving on to transcription.'
                return audioclip.filename
            except Exception as e:
                logging.error(f"Nope. Neither a valid video nor audio file: {e}")
            logging.error(f"An error occurred in 'convert_video_to_audio' (processing.py): {e}")
            return str(e)
    else:
        session['progress'] = app.config.get('steps')['ConvertedAudio']
        session['completed_step'] = 'Audio file already exists. Moving on to transcription.'
        return audio_filepath

def transcribe_audio(audio_filepath: str) -> str:
    logging.info(f"Attempting to transcribe {audio_filepath}")
    transcription_filepath = audio_filepath.replace('.wav', '.txt')
    if not os.path.exists(transcription_filepath):
        try:
            # transcribe audio file                                                         
            r = sr.Recognizer()
            with sr.AudioFile(audio_filepath) as source:
                audio = r.record(source)
                try:
                    text = r.recognize_whisper(audio)
                    # save transcription to file
                    with open(transcription_filepath, 'w') as f:
                        f.write(text)
                    logging.info(f"Transcript is {text}")
                    session['progress'] = app.config.get('steps')['Transcribed']
                    session['completed_step'] = 'Transcription complete. Moving on to summarization.'
                    return text
                except Exception as e:
                    logging.error(f"An error occurred inside transcribing {audio_filepath} (processing.py): {e}")
                    return str(e)
        except Exception as e:
            logging.error(f"An error occurred with transcribing {audio_filepath} (processing.py): {e}")
            return str(e)
    else:
        with open(transcription_filepath, 'r') as f:
            return f.read()
        
def is_file_empty(filepath :str) -> bool:
    return not os.path.exists(filepath) or os.path.getsize(filepath) == 0

def count_words_in_html_file(filepath: str) -> int:
    # if the file doesn't exist, return true
    if not os.path.exists(filepath):
        return 0
    with open(filepath, 'r') as f:
        content = f.read()
    soup = BeautifulSoup(content, 'html.parser')
    text = soup.get_text()
    words = text.split()
    return len(words)

def create_blog(
        title :str = None,
        transcript :str = None, 
        summary :str = None, 
        blog_filepath :str = None,
        word_count :int = 2500
        ) -> str:
    logging.info(f"Creating a blog post from the transcript and summary.")
    blog_content = blog_filepath
    if is_file_empty(blog_content) and count_words_in_html_file(blog_content) < word_count-(word_count*.2): # We'll give it a 20% buffer
        # We'll have the first call to openai to create an outline
        outline_fn = blog_filepath.replace('.md', '-outline.md')
        call_openai(prompt=f"This is the transcript: {transcript} and the summary you created {summary}.", type="blog-outline", filepath=outline_fn)

        session['progress'] = app.config.get('steps')['Outlined']
        session['completed_step'] = 'Blog outline created. Moving on to blog creation.'

        with open(outline_fn, 'r') as f:
            sections = [line.strip() for line in f.readlines()]

        # Calculate the number of sections we can have based on the word count
        words_per_section = word_count // len(sections)

        # Create the h1 tag for the blog post
        blog_title = f"<h1>{title}</h1>"
        with open(blog_content, 'w') as f:
            f.write(blog_title)

        # Now we'll iterate through the sections it gave us the first time
        for section in sections:
            if is_file_empty(blog_filepath):
                with open(outline_fn, 'w') as f:
                    f.write(f"")
            blog_section = call_openai(prompt=f"Write the section about {section}. Make sure you start with the section heading as an h2 tag. This section should be approximately {words_per_section} words minimum.", type="blog-section", filepath=blog_content)
            logging.info(f"Blog section: {blog_section}")

        # Read the blog file so we can return it
        with open(blog_content, 'r') as f:
            blog = f.read()

        # Cleanup the blog outline and blog section files


        # and now, we'll put it all together in a blog post
        return blog
    else:
        with open(blog_content, 'r') as f:
            return f.read()

def call_openai(
        prompt :str, 
        filepath :str,
        type :str ="summary", 
        model :str ="gpt-4-turbo-preview",
        temperature :float =0.3,
        max_tokens :int =2500,
        top_p :float =1.0
        ) -> str:
    logging.info(f"Is the file we are using empty? {is_file_empty(filepath)}")
    #Check if summary file exists and is not empty but only if the type is summary. Otherwise, we'll call OpenAI:
    if (is_file_empty(filepath) and type == "summary") or type != "summary":
        logging.info(f"Our file does not exist: {filepath}")
        try:
            logging.info(f"Calling OpenAI API with prompt: {prompt}")
            client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

            # Define a dictionary to map types to their corresponding messages
            type_messages = {
                'blog-outline': [{
                    "role": "system",
                    "content": "Based on this transcript, I'm going to write a blog post. I'll start with an introduction, then move on to the body which will touch on each of the topics in the transcript, and finally, I'll end with a conclusion. The tone should be conversational at an 8th grade (14 year old) reading level and should never use the word 'delve' or its variants, 'moreover', 'furthermore' or anything like that. Keep in mind, these videos are from my perspective so don't use terms like 'presenter' or 'speaker' because I'm the one speaking. We'll assume the audience is already familiar with the presenter so don't include any summaries of them. Give me a list of the sections for the blog post and return them to me as a list so I can have you iterate through them in later prompts. Do not include anything in your response other than the sections."
                }],
                'blog-section': [{
                    "role": "system",
                    "content": "Based on the transcript and the section outline you created, let's write a blog post. Remember, the tone should be conversational at an 8th grade (14 year old) reading level and should never use the word 'delve' or its variants, 'moreover', 'furthermore' or anything like that. Don't start sections with anything like 'hey there' or hi' because we are just continuing the blog post. Keep in mind, these videos are from my perspective so don't use terms like 'presenter' or 'speaker' because I'm the one speaking. Put it in an html format starting with an h2 tag, but don't end with a closing body tag."
                }],
                'summary': [{
                    "role": "system",
                    "content": "You are going to only answer in html format. You'll start with an 'h2' tag and continue through. Do not end with a closing body tag. The tone should be conversational at an 8th grade (14 year old) reading level and should never use the word 'delve' or its variants, 'moreover', 'furthermore' or anything like that. Keep in mind, these videos are from my perspective so don't use terms like 'presenter' or 'speaker' because I'm the one speaking. We'll assume the audience is already familiar with me as the presenter so don't include any summaries of their information during the introduction."
                }],
                # Add more types and their messages here...
            }

            # Get the messages for the given type
            messages = type_messages.get(type)

            # Add the user's prompt to the messages
            if messages is not None:
                type_messages[type].append({
                    "role": "user",
                    "content": prompt
                })

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p
            ).choices[0].message.content

            # Add the response to the messages
            type_messages[type].append({
                "role": "assistant",
                "content": response
            })

            logging.info(f"Response from OpenAI: {response}")

            try:
                with open(filepath, 'a') as f:
                    if type == 'blog-outline':
                        response = '\n'.join([line[2:] for line in response.strip().split('\n')])
                    elif type == 'blog-section':
                        response = response.replace("```html\n", "").replace("```", "")

                    logging.info(f"Formatted response: {response}")
                    f.write(response)
                    return(response)
            except Exception as e:
                logging.error(f"An error occurred saving {filepath}")
                return str(e)
        except Exception as e:
            logging.error(f"An error occurred inside call_openai (processing.py): {e}")
            return str(e)
    else:
        logging.info(f"Summary file exists ({filepath}) and is not empty so we will use it.")
        with open(filepath, 'r') as f:
            return md.markdown(text=f.read(), extensions=['extra'])
        
def call_dalle(
        model :str = "dall-e-3",
        prompt :str = None,
        size :str = "1792x1024",
        quality :str = "better",
        n :int = 1,
        filename :str = "image.png"
        ) -> str:
    # Is there already a header image?
    if is_file_empty(filename):
        logging.info(f"We don't have a header image yet. Let's get one.")
        # Call DALL-E
        try:
            logging.info(f"Calling DALL-E with prompt: {prompt}")
            dalle = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
            response = dalle.images.generate(
                model=model,
                prompt=prompt,
                size= size,
                quality=quality,
                n=n
            )
            logging.info(f"Response from DALL-E: {response}")
            image_url = response.data[0].url
            # Download the image
            response = requests.get(image_url)
            with open(filename, 'wb') as f:
                f.write(response.content)
                session['progress'] = 55.56
                session['completed_step'] = 'Header image created.'
            return filename
        except Exception as e:
            logging.error(f"An error occurred inside call_dalle (processing.py): {e}")
            return str(e)
    else:
        logging.info(f"Header image exists ({filename}) and is not empty so we will use it.")
        return filename