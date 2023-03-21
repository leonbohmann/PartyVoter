import pyautogui
from flask import Flask
app = Flask(__name__)

count = 0

@app.route('/upvote')
def upvote():
    global count
    count += 1
    return str(count)

@app.route('/downvote')
def downvote():
    global count
    count = count - 1      
    
    print(f"Someone downvoted current track. Count: {count}")
    
    if count < -4:
        pyautogui.press("nexttrack")
        count = 0

      
    return str(count)

@app.route('/count')
def get_count():
    return str(count)

if __name__ == '__main__':
    app.run()    