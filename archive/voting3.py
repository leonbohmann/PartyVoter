from flask import Flask, render_template_string, session
from datetime import datetime, timedelta
import pyautogui

lvtkey = 'last_vote_time'

app = Flask(__name__)
app.secret_key = 'UpJ5WTyPW43krsfuxQTsHdojLaQqt3q'

COOLDOWN_TIME = 10

count = 0

@app.route('/')
def index():
    global count
    now = datetime.now()
    last_vote_time = session.get(lvtkey).replace(tzinfo=None)
    if last_vote_time:
        cooldown_active = (now - last_vote_time) < timedelta(seconds=10)
    else:
        cooldown_active = False
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
            <body onload="updateCooldown({{cooldown_seconds}})">
                
                <button id="upvote" class="up" onclick="vote('upvote')"><span class="up">👍</span></button> 
                <br>
                <h1>Current count: {{ count }}</h1>
                <br>
                <button id="downvote" class="down" onclick="vote('downvote')"><span class="down">👎</span></button>

                <p id="result"></p>
                
                <script>
                    function vote(voteType) {
                        fetch('/' + voteType)
                            .then(response => response.text())
                            .then(data => {
                                window.location.reload();
                                return data;
                            }).then(data => {
                                document.getElementById("result").textContent = data;
                            }).then(x => {
                                setTimeout(function() {
                                        location.reload();
                                    }, 10000);
                            });                            
                    }
                    
                </script>

            </body>
        </html>
    ''', count=count, cooldown_active=cooldown_active)

@app.route('/upvote')
def upvote():
    global count
    last_vote_time = session.get(lvtkey).replace(tzinfo=None)
    now = datetime.now()
    if last_vote_time and now - last_vote_time < timedelta(seconds=10):
        return 'You must wait {} seconds before voting again.'.format(int(10 - (now - last_vote_time).total_seconds()))
    else:
        session[lvtkey] = now
        count += 1
        return str(count)

@app.route('/downvote')
def downvote():
    global count
    last_vote_time = session.get(lvtkey).replace(tzinfo=None)
    now = datetime.now()
    if last_vote_time and now - last_vote_time < timedelta(seconds=COOLDOWN_TIME):
        return 'You must wait {} seconds before voting again.'.format(COOLDOWN_TIME)
    else:
        session[lvtkey] = now
        count += 1
                
        if count < -4:
            pyautogui.press("nexttrack")
            count = 0
            
        return str(count)
        

if __name__ == '__main__':
    app.run()