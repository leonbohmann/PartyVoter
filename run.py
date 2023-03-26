import asyncio
import base64
import json
import threading
import time
import uuid
from datetime import datetime, timedelta

from flask import Flask, Response, make_response, render_template, request, session
from flask_sessions import RedisSessionInterface
from flask_sqlalchemy import SQLAlchemy
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSession as MediaSession,
)
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
)
from winsdk.windows.storage.streams import IRandomAccessStreamReference

# initialization
app = Flask(__name__)
app.secret_key = 'XaHN9wNidcRj4i2YmPbYq7XWgSeLYjr'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///voter.db'
db = SQLAlchemy(app)

COOLDOWN_TIME_SECONDS = 15
MAX_DOWNVOTES = 3
SITE_NAME = "PartyVoter"
SERVER_PORT = 8099
SERVER_BIND = "0.0.0.0"

VOTE_MODE = 'timed' # modes: 'oncepertrack', 'timed'

# globally used variables
current_rating = 0              # rating for current song
last_title = ''                 # used to determine if song changed
detected_song_change = False    # flag to indicate if last song changed

class Voter(db.Model):
    """
    Database model for per-user objects in database. Inherits from db.Model
    so it can synchronize automatically.
    """
    id = db.Column(db.Integer, primary_key=True, unique=True)
    username = db.Column(db.String(50))
    songs = db.Column(db.Text)
    
    def __repr__(self):
        return f'<Voter {self.username}>'

async def get_session() -> MediaSession:
    """Returns the current media session.

    Returns:
        MediaSession: The current session.
    """
    sessions = await MediaManager.request_async()
    return sessions.get_current_session()

async def get_media_info() -> dict | None:
    """Returns an array of information about the current media, if any.

    Returns:
        dict | None: A dictionary with information or none, if no session is available.
        
    Reference:
        https://stackoverflow.com/a/66037406/5192178
    """
    current_session = await get_session()
    if current_session:  # there needs to be a media session running
        info = await current_session.try_get_media_properties_async()

        # song_attr[0] != '_' ignores system attributes
        info_dict = {song_attr: info.__getattribute__(song_attr) \
            for song_attr in dir(info) if song_attr[0] != '_'}

        # converts winrt vector to list
        info_dict['genres'] = list(info_dict['genres'])

        return info_dict

    return None

async def next_track():
    """Tries to skip to the next track."""
    session = await get_session()
    if session:
        await session.try_skip_next_async()
        
async def add_song_to_user():
    """Add the currently playing song to users voter data store."""
    music_data = await get_media_info()
    liked_song = {'artist': music_data["artist"], 'title': music_data["title"]}
    
    voter = try_get_user_voter()
    songs = json.loads(voter.songs)    
    songs.append(liked_song)
    voter.songs = json.dumps(songs)
    db.session.commit()
    
def try_get_user_id() -> str | None:
    """Returns the unique user id from cookie.

    Returns:
        str | None: User UUID as string.
    """
    if 'userID' in request.cookies:
        return str(request.cookies.get('userID'))    

def try_get_cooldown_time() -> int:
    """Calculate the cooldown time from the last vote time and the current time.

    Returns:
        int: Seconds left of cooldown.
    """
    
    if 'last_vote_time' in session:
        last_vote_time = session['last_vote_time']
    else:
        last_vote_time = session['last_vote_time'] = datetime.min
        
    last_vote_time = last_vote_time.replace(tzinfo=None)
    time_since_vote = datetime.now() - last_vote_time
    seconds_since_vote = time_since_vote.total_seconds()
    cooldown_remaining = COOLDOWN_TIME_SECONDS - seconds_since_vote
    
    return cooldown_remaining if cooldown_remaining > 0 else 0

def try_get_user_voter() -> Voter | None:
    """Tries to retrieve the voter object from database.

    Returns:
        db.Model: Voter model from database.
    """
    user_id = try_get_user_id()
    if user_id:
        voter = Voter.query.filter_by(username=user_id).first()    
        return voter

def remove_key_from_sessions(key):
    # get the session interface
    session_interface = app.session_interface

    # check if the session interface is a RedisSessionInterface
    if isinstance(session_interface, RedisSessionInterface):
        # get the Redis instance
        redis = session_interface.redis

        # get all session keys
        session_keys = redis.keys(f'{session_interface.key_prefix}:*')

        # iterate over session keys and remove the key from each session
        for session_key in session_keys:
            session_data = redis.get(session_key)
            if session_data is not None:
                session = session_interface.session_class(pickler=session_interface._get_picked(),
                                                           data=session_data)
                session.pop(key, None)
                redis.set(session_key, session_interface.get_signer().sign(session.dumps()))

def register_user(uid: str):
    """Create the voter object for a user uuid.

    Args:
        uid (str): Unique user id.
    """
    new_voter = Voter(username=uid, songs='[]')
    
    db.session.add(new_voter)
    db.session.commit()
    
    print(f'New user with id "{uid}".')
    
def reset_rating_on_song_change():
    """Self-requeuing function to check for track title changes."""
    global current_rating, last_title, detected_song_change
    media_info  = asyncio.run(get_media_info())
    
    if media_info and last_title != media_info['title']:
        print("Detected song change, resetting counter.")
        current_rating = 0
        last_title = media_info['title']
        get_thumb()
        detected_song_change = True
        remove_key_from_sessions('last_voted_track')
    else:
        detected_song_change = False   
    
    # reschedule self
    threading.Timer(5.0, reset_rating_on_song_change).start()

def get_thumb():
    """Saves the current playing media thumbnail to a local file."""
    from winsdk.windows.storage.streams import Buffer, DataReader, InputStreamOptions


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


@app.route('/liked')
def get_liked_songs():
    voter = try_get_user_voter()
    songs = json.loads(voter.songs)
    return render_template('liked.html', songs = enumerate(songs), \
        SITE_NAME = SITE_NAME)

def can_user_vote() -> bool:
    # timed: allow user vote every COOLDOWN_TIME_SECONDS
    if VOTE_MODE == 'timed':
        now = datetime.now()
        last_vote_time = session.get('last_vote_time').replace(tzinfo=None)
        return last_vote_time \
            and now - last_vote_time > timedelta(seconds=COOLDOWN_TIME_SECONDS)
                        
    elif VOTE_MODE == 'oncepertrack':
        media = asyncio.run(get_media_info())
        if media and 'last_voted_track' not in session:
            session['last_voted_track'] = media['title']
            return True
        elif media and 'last_voted_track' in session:
            current_title = media['title']
            return current_title != session['last_voted_track']
                                   
        return False


def user_voted() -> None:
    media =asyncio.run( get_media_info() )
    
    if VOTE_MODE == 'timed':
        session['last_vote_time'] = datetime.now()
    elif VOTE_MODE == 'oncepertrack' and media:
        session['last_voted_track'] = media['title']
    else:
        raise Exception("Voting not possible!")

@app.route('/vote', methods=['POST'])
def vote():
    global current_rating
    now = datetime.now()
    last_vote_time = session.get('last_vote_time').replace(tzinfo=None)
    if not can_user_vote():
        time_left = COOLDOWN_TIME_SECONDS - (now - last_vote_time).seconds
        print("DEBUG: Vote not possible.")
        return {'success': False, 'time_left': time_left, 'mode': VOTE_MODE}
    else:
        user_voted()
        if request.form['vote'] == 'up':
            current_rating += 1
            asyncio.run(add_song_to_user())
        elif request.form['vote'] == 'down':
            current_rating -= 1
            
        print(f"DEBUG: {request.form['vote']}-Vote went through. Rating is now: {current_rating}")
        
        if current_rating <= -MAX_DOWNVOTES:
            asyncio.run(next_track())
            current_rating = 0
            print("Current track voted away!")
            
        return {'success': True, 'time_left': COOLDOWN_TIME_SECONDS, 'mode': VOTE_MODE}

@app.route('/rating')
def rating():
    def eventStream():
        global current_rating
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
            if not data0: 
                continue
            data = {}
            data['artist'] = data0['artist']
            data['title'] = data0['title']
            with open("static/media_thumb.jpg", 'rb') as fobj:                
                data['src'] = base64.b64encode(fobj.read()).decode('utf-8')
            
            data['changed'] = detected_song_change
            yield f"data: {json.dumps(data)}\n\n"
            time.sleep(2)
    
    return Response(eventStream(), mimetype="text/event-stream")

@app.route('/')
def index():
    db.create_all()
    global current_rating
    
    if not session.get('last_vote_time'):
        session['last_vote_time'] = datetime.min
    
    resp = make_response(render_template('index.html', current_rating=current_rating, \
        COOLDOWN_TIME=COOLDOWN_TIME_SECONDS, SITE_NAME = SITE_NAME, \
            cooldown_remaining=try_get_cooldown_time()))
    
    # check if cookie and voter object are available
    if not try_get_user_id() or not try_get_user_voter():
        uid = str(uuid.uuid1())
        register_user(uid)
        resp.set_cookie('userID', uid)
    
    return resp

if __name__ == '__main__':
    media_info  = asyncio.run(get_media_info())
    if media_info:
        last_title = media_info['title']
    # background task to reset counter when song changes
    threading.Timer(1.0, reset_rating_on_song_change).start()
    
    app.run(host=SERVER_BIND, port=SERVER_PORT)
