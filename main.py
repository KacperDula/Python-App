import os
import random
from string import ascii_uppercase
from datetime import datetime
from collections import defaultdict
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, join_room, leave_room, send

# Initialize Flask app
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# File upload configuration
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB

# Initialize SocketIO with CORS support
socketio = SocketIO(app, cors_allowed_origins="*")

# Room management
rooms = defaultdict(dict)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def generate_unique_code(length):
    """Generate unique room code"""
    while True:
        code = ''.join(random.choice(ascii_uppercase) for _ in range(length))
        if code not in rooms:
            return code

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file uploads"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        file_url = url_for('static', filename=f"uploads/{filename}", _external=True)
        return jsonify({
            'fileUrl': file_url,
            'fileType': file.content_type
        }), 200
        
    return jsonify({'error': 'Invalid file type'}), 400

@app.route("/", methods=["POST", "GET"])
def home():
    """Homepage with room joining/creation"""
    session.clear()
    if request.method == "POST":
        name = request.form.get("name")
        code = request.form.get("code")
        join = request.form.get("join", False)
        create = request.form.get("create", False)

        if not name:
            return render_template("home.html", error="Please enter a name.", code=code, name=name)

        if join != False and not code:
            return render_template("home.html", error="Please enter a room code.", code=code, name=name)
        
        room = code
        if create != False:
            room = generate_unique_code(4)
            rooms[room] = {"members": set(), "messages": []}
        elif code not in rooms:
            return render_template("home.html", error="Room does not exist.", code=code, name=name)
        
        session["room"] = room
        session["name"] = name
        return redirect(url_for("room"))

    return render_template("home.html")

@app.route("/room")
def room():
    """Chat room interface"""
    room = session.get("room")
    name = session.get("name")
    if room is None or name is None or room not in rooms:
        return redirect(url_for("home"))
    return render_template("room.html", code=room, messages=rooms[room]["messages"], name=name)

@socketio.on("message")
def handle_message(data):
    """Handle real-time messages"""
    room = session.get("room")
    if room not in rooms:
        return
    
    content = {
        "name": session.get("name"),
        "message": data["data"],
        "time": datetime.now().strftime("%H:%M:%S"),
        "is_file": data.get("isFile", False),
        "file_type": data.get("fileType", None)
    }
    send(content, to=room)
    rooms[room]["messages"].append(content)
    print(f"{session.get('name')} sent message in {room}")

@socketio.on("connect")
def handle_connect(auth):
    """Handle new connections"""
    room = session.get("room")
    name = session.get("name")
    if not room or not name:
        return
    if room not in rooms:
        leave_room(room)
        return
    
    join_room(room)
    rooms[room]["members"].add(name)
    send_user_update(room)
    send({
        "name": name,
        "message": "has entered the room",
        "time": datetime.now().strftime("%H:%M:%S"),
        "is_file": False
    }, to=room)
    print(f"{name} joined {room}")

@socketio.on("disconnect")
def handle_disconnect():
    """Handle disconnections"""
    room = session.get("room")
    name = session.get("name")
    if room in rooms and name in rooms[room]["members"]:
        rooms[room]["members"].remove(name)
        send_user_update(room)
        send({
            "name": name,
            "message": "has left the room",
            "time": datetime.now().strftime("%H:%M:%S"),
            "is_file": False
        }, to=room)
        print(f"{name} left {room}")
        
        if len(rooms[room]["members"]) == 0:
            del rooms[room]

def send_user_update(room):
    """Broadcast user list updates"""
    socketio.emit("user-update", {
        "count": len(rooms[room]["members"]),
        "users": list(rooms[room]["members"])
    }, to=room)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
