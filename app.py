# Standard library imports
import time
import logging
import json
from urllib.parse import urlparse

# Flask framework and extensions
from flask import Flask, render_template, request, session, Response, send_from_directory
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed

# Werkzeug (WSGI utility library used by Flask)
from werkzeug.datastructures import FileStorage

# WTForms (form handling library)
from wtforms import StringField, SubmitField
from wtforms.validators import ValidationError

# Local application imports
from scripts.processing import *

app = Flask(__name__)
app.secret_key = 'secret'
app.config['UPLOAD_FOLDER'] = os.path.abspath('./uploads')
app.config['steps'] = {
    "Init Form": 0,
    "Downloaded": 12.5,
    "ConvertedAudio": 25,
    "Transcribed": 37.5,
    "Summarized": 50,
    "Outlined": 62.5,
    "Content": 75,
    "HeaderImage": 87.5,
    "Completed": 100
}

logging.basicConfig()
fh = logging.FileHandler(f'logs/blogarize.log', mode='w')
fh.setLevel(logging.DEBUG)  # Set the handler's level to DEBUG
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(lineno)d - %(funcName)s - %(message)s')
fh.setFormatter(formatter)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)  # Set the logger's level to DEBUG
logger.addHandler(fh)
logging.debug("app.py: And away we go!")

class VideoForm(FlaskForm):
    logging.info('New VideoForm class object created.')

    youtube_link = StringField('Youtube Link', default="https://www.youtube.com/watch?v=cAgZFEhJrKk")
    mp4_upload = FileField('Upload MP4')
    mp4_size = StringField('MP4 Size', default="0")
    submit = SubmitField('Submit')

    def validate_youtube_link(form, field):
        logging.info(f"Validating the YouTube link: {field.data}")
        """Check if the URL domain is youtube.com"""
        youtube_link = field.data
        if youtube_link != '':
            domain = urlparse(youtube_link).netloc
            if not domain.endswith('youtube.com'):
                logging.error(f"Invalid YouTube URL: {domain}")
                raise ValidationError('Invalid YouTube URL')
                
    def validate_mp4_upload(form, field):
        logging.info(f"Validating the MP4 upload {field.data}")
        """Check if the file is MP4 or returns an error"""
        file = field.data
        if file != '':
            if isinstance(file, FileStorage):
                logging.info(f"File is a file object: {file}")
                if not file.filename.lower().endswith('.mp4'):
                    raise ValidationError('Invalid file format. Please, upload a .mp4 file')

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    form = VideoForm()
    global download_progress
    download_progress = 0
    
    if form.validate_on_submit():
        if form.youtube_link.data and form.mp4_upload.data:
            return "Please provide only one input: either a YouTube link or an MP4 file.", 400

        session['progress'] = 0
        session['current_step'] = 'Downloading video.'

        file_name = ""
        if form.youtube_link.data:
            logging.info(f"Processing YouTube Link: {form.youtube_link.data}")
            video = get_youtube_video(form.youtube_link.data)
            title = video[0].title
            file_name = download_youtube_video(video[0], video[1], app.config['UPLOAD_FOLDER'])
            session['progress'] = app.config.get('steps')['Downloaded']
            session['current_step'] = 'YouTube Video Downloaded. Converting to audio...'
        elif form.mp4_upload.data:
            logging.info(f"Saving uploaded file: {form.mp4_upload.data}")
            mp4_size = int(form.mp4_size.data)
            file = save_uploaded_file(form.mp4_upload.data, app.config['UPLOAD_FOLDER'], mp4_size)
            file_name = file[1]
            title = file[0]
            session['progress'] = app.config.get('steps')['Downloaded']
            session['current_step'] = 'MP4 File Uploaded. Converting to audio...'
      
        if file_name.endswith('.mp4'):
            logging.info(f"Video File: {file_name}")
            video_filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_name)
            audio_filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_name.replace('.mp4', '.wav'))
            convert_video_to_audio(video_filepath, audio_filepath)
            if audio_filepath.endswith('.wav'):
                logging.info(f"Audio file: {audio_filepath}")
                # Transcribe the audio to text
                transcript = transcribe_audio(audio_filepath)
                # Check if transcription was a success
                if not transcript.startswith('Could not transcribe'):
                    summary_filepath = audio_filepath.replace('.wav', '.md')
                    # Summarize the transcription
                    summary = call_openai(f"Give me an outline and summary of this text: {transcript}", summary_filepath)
                    # Check if summary was a success
                    if not summary.startswith('Could not summarize'):
                        session['progress'] = app.config.get('steps')['Summarized']
                        session['current_step'] = 'Summarized. Creating a blog post from the summary.'
                        blog_filepath = audio_filepath.replace('.wav', '-blog.html')
                        blog = create_blog(title, transcript, summary, blog_filepath)
                        dalle_filepath = audio_filepath.replace('.wav', '-dalle.png')
                        call_dalle(prompt=f"Generate an image based on the blog post you created. Do not, under any circumstances, put words in this image. {summary}.", filename=dalle_filepath, model="dall-e-3", size="1792x1024", n=1, quality="hd")

                        return render_template('output.html', summary=summary, transcript=transcript, title=title, blog=blog, header_img=os.path.basename(dalle_filepath))
                    else:
                        logging.error(f"Error in summarizing: {summary}")
                        return render_template('error.html', message=summary)
                else:
                    logging.error(f"Error in transcription: {transcript}")
                    return render_template('error.html', message=transcript)
            else:
                logging.error(f"Error in converting to audio: {audio_filepath}")
                return render_template('error.html', message=audio_filepath)
        # Add an error page or message if an error occurs during processing
        return render_template('error.html', message='An error occurred during processing. Please try again.')
    return render_template('form.html', form=form)

@app.route('/download/<path:filename>')
def download(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/progress')
def progress():
    def generate():
        while True:
            progress :int = session.get('progress', 0)
            current_step :str= session.get('current_step', 'Press submit to get started.')
            yield f"data: {json.dumps({'progress': progress, 'current_step': current_step})}\n\n"
            time.sleep(1)
    return Response(generate(), mimetype="text/event-stream")

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5000, debug = True)