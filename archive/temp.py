from flask import Flask, session, request
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'your secret key'

COOLDOWN_TIME = 10  # seconds

@app.route('/vote', methods=['POST'])
def vote():
    now = datetime.now()
    last_vote_time = session.get('last_vote_time')
    if last_vote_time and now - last_vote_time < timedelta(seconds=COOLDOWN_TIME):
        return 'You must wait {} seconds before voting again.'.format(COOLDOWN_TIME)
    else:
        session['last_vote_time'] = now
        # process the vote here (e.g. call the upvote or downvote API)
        return 'Your vote has been counted.'

if __name__ == '__main__':
    app.run()