from flask import Flask, render_template_string
from datetime import datetime, timedelta

app = Flask(__name__)

count = 0
last_vote_time = datetime.min

@app.route('/')
def index():
    global count, last_vote_time
    now = datetime.now()
    cooldown_active = (now - last_vote_time) < timedelta(seconds=10)
    return render_template_string('''
        <html>
            <head>
                <style>
                    .up {
                        color: white;
                        background-color: {{ 'grey' if cooldown_active else 'green' }};
                    }
                    .down {
                        color: white;
                        background-color: {{ 'grey' if cooldown_active else 'red' }};
                    }
                    button {
                        font-size: 24px;
                        padding: 10px 20px;
                        margin-bottom: 10px;
                    }
                </style>
            </head>
            <body>
                <button class="up" onclick="vote('upvote')"><span class="up">👍</span></button> 
                <br>
                <h1>Current count: {{ count }}</h1>
                <br>
                <button class="down" onclick="vote('downvote')"><span class="down">👎</span></button>

                <script>
                    function vote(voteType) {
                        fetch('/' + voteType)
                            .then(response => response.text())
                            .then(data => {
                                window.location.reload();
                            });
                    }
                </script>

            </body>
        </html>
    ''', count=count, cooldown_active=cooldown_active)

@app.route('/upvote')
def upvote():
    global count, last_vote_time
    now = datetime.now()
    if now - last_vote_time > timedelta(seconds=10):
        last_vote_time = now
        count += 1
    return str(count)

@app.route('/downvote')
def downvote():
    global count, last_vote_time
    now = datetime.now()
    if now - last_vote_time > timedelta(seconds=10):
        last_vote_time = now
        count -= 1
    return str(count)

if __name__ == '__main__':
    app.run()