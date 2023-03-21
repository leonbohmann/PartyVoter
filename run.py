import asyncio
import json
import time
import uuid
from flask import Flask, Response, flash, make_response, session, request, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from sqlalchemy import ARRAY, String
from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager
from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSession as MediaSession
from winsdk.windows.storage.streams import IRandomAccessStreamReference
import threading
import base64

# create app
app = Flask(__name__)
app.secret_key = 'XaHN9wNidcRj4i2YmPbYq7XWgSeLYjr'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///voter.db'
db = SQLAlchemy(app)

COOLDOWN_TIME = 15  # seconds
MAX_DOWNVOTES = 3
current_rating = 0
lnr_key = 'last_known_rating'
voted = False
last_title = ''
detected_song_change = False
latest_media_thumb = 'media_thumb.jpg'

class Voter(db.Model):
    id = db.Column(db.Integer, primary_key=True, unique=True)
    username = db.Column(db.String(50))
    songs = db.Column(db.Text)
    
    def __repr__(self):
        return f'<Voter {self.username}>'

async def get_session() -> MediaSession:
    sessions = await MediaManager.request_async()
    return sessions.get_current_session()

# in the background, check for pauses in the 
async def get_media_info():
    current_session = await get_session()
    if current_session:  # there needs to be a media session running
        info = await current_session.try_get_media_properties_async()

        # song_attr[0] != '_' ignores system attributes
        info_dict = {song_attr: info.__getattribute__(song_attr) \
            for song_attr in dir(info) if song_attr[0] != '_'}

        # converts winrt vector to list
        info_dict['genres'] = list(info_dict['genres'])

        return info_dict

    # It could be possible to select a program from a list of current
    # available ones. I just haven't implemented this here for my use case.
    # See references for more information.
    return None

async def next_track():
    session = await get_session()
    if session:
        await session.try_skip_next_async()

async def prev_track():
    session = await get_session()
    if session:
        await session.try_skip_previous_async()        

async def add_song_to_user():
    """Add the currently playing song to users voter data store."""
    music_data = await get_media_info()
    voter = get_user_voter()
    songs = json.loads(voter.songs)
    liked_song = {'artist': music_data["artist"], 'title': music_data["title"]}
    songs.append(liked_song)
    voter.songs = json.dumps(songs)
    db.session.commit()
    
@app.route('/liked')
def get_liked_songs():
    voter = get_user_voter()
    songs = json.loads(voter.songs)
    return render_template('liked.html', songs = enumerate(songs))

def get_user_id() -> str | None:
    """Returns the unique user id from cookie.

    Returns:
        str | None: User UUID as string.
    """
    if 'userID' in request.cookies:
        return str(request.cookies.get('userID'))    

def get_user_voter() -> Voter | None:
    """Tries to retrieve the voter object from database.

    Returns:
        db.Model: Voter model from database.
    """
    user_id = get_user_id()
    if user_id:
        voter = Voter.query.filter_by(username=user_id).first()    
        return voter

@app.route('/')
def index():
    db.create_all()
    global current_rating
    
    if not session.get('last_vote_time'):
        session['last_vote_time'] = datetime.min
    
    resp = make_response(render_template('index.html', current_rating=current_rating,\
        COOLDOWN_TIME=COOLDOWN_TIME))
    
    # check if cookie and voter object are available
    if not get_user_id() or not get_user_voter():
        uid = str(uuid.uuid1())
        register_user(uid)
        resp.set_cookie('userID', uid)
        flash("New user logged in!")
    
    return resp

def register_user(uid: str):
    """Create the voter object for a user uuid.

    Args:
        uid (str): Unique user id.
    """
    new_voter = Voter(username=uid, songs='[]')
    
    db.session.add(new_voter)
    db.session.commit()
    
    print(f'New user with id "{uid}".')

@app.route('/vote', methods=['POST'])
def vote():
    global current_rating, voted
    now = datetime.now()
    last_vote_time = session.get('last_vote_time').replace(tzinfo=None)
    if last_vote_time and now - last_vote_time < timedelta(seconds=COOLDOWN_TIME):
        time_left = COOLDOWN_TIME - (now - last_vote_time).seconds
        return {'success': False, 'time_left': time_left}
    else:
        session['last_vote_time'] = now
        if request.form['vote'] == 'up':
            current_rating += 1
            asyncio.run(add_song_to_user())
        elif request.form['vote'] == 'down':
            current_rating -= 1
            
        if current_rating < -4:
            asyncio.run(next_track())
            current_rating = 0
            
        voted = True
        return {'success': True}

@app.route('/rating')
def rating():
    def eventStream():
        global current_rating, voted
        while True:
            # Poll data from the database
            # and see if there's a new message
            yield f"data: {current_rating}\n\n"
            
            time.sleep(2)
    
    return Response(eventStream(), mimetype="text/event-stream")

@app.route('/media')
def current_media():
    def eventStream():        
        global detected_song_change
        while True:
            # Poll data from the database
            # and see if there's a new message
            data0 = asyncio.run(get_media_info())
            data = {}
            data['artist'] = data0['artist']
            data['title'] = data0['title']
            with open("static/media_thumb.jpg", 'rb') as fobj:                
                data['src'] = base64.b64encode(fobj.read()).decode('utf-8')
            
            data['changed'] = detected_song_change
            yield f"data: {json.dumps(data)}\n\n"
            time.sleep(2)
    
    return Response(eventStream(), mimetype="text/event-stream")



def reset_rating_on_song_change():
    global current_rating, last_title, detected_song_change
    media_info  = asyncio.run(get_media_info())
    
    if media_info and last_title != media_info['title']:
        print("Detected song change, resetting counter.")
        current_rating = 0
        last_title = media_info['title']
        get_thumb()
        detected_song_change = True
    else:
        detected_song_change = False   
    
    # reschedule self
    threading.Timer(5.0, reset_rating_on_song_change).start()

def get_thumb():
    from winsdk.windows.storage.streams import \
            DataReader, Buffer, InputStreamOptions


    async def read_stream_into_buffer(stream_ref , buffer):
        readable_stream = await stream_ref.open_read_async()
        readable_stream.read_async(buffer, buffer.capacity, \
            InputStreamOptions.READ_AHEAD)

    current_media_info = asyncio.run(get_media_info())

    # create the current_media_info dict with the earlier code first
    thumb_stream_ref:IRandomAccessStreamReference = current_media_info['thumbnail']
    
    # 5MB (5 million byte) buffer - thumbnail unlikely to be larger
    thumb_read_buffer = Buffer(5000000)

    # copies data from data stream reference into buffer created above
    asyncio.run(read_stream_into_buffer(thumb_stream_ref, thumb_read_buffer))

    # reads data (as bytes) from buffer
    buffer_reader = DataReader.from_buffer(thumb_read_buffer)
    # byte_buffer = buffer_reader.read_bytes(8)
    byte_buffer = buffer_reader.read_buffer(thumb_read_buffer.length)

    with open('static/media_thumb.jpg', 'wb+') as fobj:
        fobj.write(bytearray(byte_buffer))

if __name__ == '__main__':
    media_info  = asyncio.run(get_media_info())
    if media_info:
        last_title = media_info['title']
    # background task to reset counter when song changes
    threading.Timer(1.0, reset_rating_on_song_change).start()
    
    app.run(host="0.0.0.0", port=8099)
