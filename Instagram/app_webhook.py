from flask import Flask
from dotenv import load_dotenv
from Instagram.webhook import instagram_bp
load_dotenv()
app = Flask(__name__)
app.register_blueprint(instagram_bp)

if __name__ == "__main__":
    app.run(port=5000, debug=True)