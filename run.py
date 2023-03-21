import asyncio
import json
import time
from flask import Flask, Response, session, request, render_template, jsonify
from datetime import datetime, timedelta
from winsdk.windows.media.control import \
    GlobalSystemMediaTransportControlsSessionManager as MediaManager
from winsdk.windows.media.control import \
    GlobalSystemMediaTransportControlsSession as MediaSession
from winsdk.windows.storage.streams import \
    IRandomAccessStreamReference
import threading
import base64

# create app
app = Flask(__name__)
app.secret_key = 'XaHN9wNidcRj4i2YmPbYq7XWgSeLYjr'

COOLDOWN_TIME = 3  # seconds
current_rating = 0
lnr_key = 'last_known_rating'
voted = False
last_title = ''
detected_song_change = False
latest_media_thumb = 'media_thumb.jpg'

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

@app.route('/')
def index():
    global current_rating
    if not session.get('last_vote_time'):
        session['last_vote_time'] = datetime.min
    
    return render_template('index.html', current_rating=current_rating)

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
    
    app.run(host="0.0.0.0")
