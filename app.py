
from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Free Storage Server Working'

# Remove the if __name__ == "__main__" block since gunicorn will handle the app
