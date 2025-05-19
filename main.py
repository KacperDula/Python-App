# Import required modules from Flask for web framework and utility functions
from flask import Flask, render_template, request, session, redirect, url_for, jsonify

# Import real-time messaging features from Flask-SocketIO
from flask_socketio import join_room, leave_room, send, SocketIO

# Import modules for generating random codes and managing strings
import random
from string import ascii_uppercase

# Import defaultdict to create default dictionary structure
from collections import defaultdict

# Import os for file handling
import os

# Utility to safely handle filenames
from werkzeug.utils import secure_filename

# Import datetime to timestamp messages and files
from datetime import datetime

# Initialize the Flask app
app = Flask(__name__)

# Set a secret key to use session data securely
app.config["SECRET_KEY"] = "hjhjsdahhds"

# Directory to store uploaded files
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Allowed file types for uploads
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# Max allowed file size (5 MB)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

# Initialize SocketIO for real-time communication
socketio = SocketIO(app)

# Dictionary to store room data (members and messages)
rooms = defaultdict(dict)

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Check if uploaded file is allowed based on extension
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Generate a unique room code that doesn't conflict with existing ones
def generate_unique_code(length):
    while True:
        code = ""
        for _ in range(length):
            code += random.choice(ascii_uppercase)
        if code not in rooms:
            break
    return code

# Route to handle file uploads
@app.route('/upload', methods=['POST'])
def upload_file():
    # Check if a file is included in the request
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
        
    # Retrieve the file from the request
    file = request.files['file']

    # Check if a filename was provided
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # If file is valid and allowed
    if file and allowed_file(file.filename):
        # Create a secure and unique filename using timestamp
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        
        # Build full path to save the file
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Save the file to disk
        file.save(filepath)
        
        # Create a URL to access the uploaded file
        file_url = url_for('static', filename=f"uploads/{filename}")
        
        # Return file URL and its MIME type as JSON response
        return jsonify({
            'fileUrl': file_url,
            'fileType': file.content_type
        }), 200
        
    # If the file type is not allowed
    return jsonify({'error': 'Invalid file type'}), 400

# Main homepage route
@app.route("/", methods=["POST", "GET"])
def home():
    # Clear any previous session data
    session.clear()
    
    # Handle form submission
    if request.method == "POST":
        # Get user name and room code from form
        name = request.form.get("name")
        code = request.form.get("code")
        
        # Check if the user wants to join or create a room
        join = request.form.get("join", False)
        create = request.form.get("create", False)

        # Validate that name is provided
        if not name:
            return render_template("home.html", error="Please enter a name.", code=code, name=name)

        # If joining a room, ensure room code is provided
        if join != False and not code:
            return render_template("home.html", error="Please enter a room code.", code=code, name=name)
        
        room = code

        # If creating a room, generate a new unique room code
        if create != False:
            room = generate_unique_code(4)
            rooms[room] = {"members": set(), "messages": []}
        
        # If trying to join a room that doesn't exist
        elif code not in rooms:
            return render_template("home.html", error="Room does not exist.", code=code, name=name)
        
        # Store room and name in session
        session["room"] = room
        session["name"] = name

        # Redirect user to the chat room
        return redirect(url_for("room"))

    # Render the homepage template
    return render_template("home.html")

# Route for the chat room page
@app.route("/room")
def room():
    # Get room and user name from session
    room = session.get("room")
    name = session.get("name")

    # If session is invalid or room doesn't exist, redirect to home
    if room is None or name is None or room not in rooms:
        return redirect(url_for("home"))

    # Render the chat room with room code, messages, and user name
    return render_template("room.html", code=room, messages=rooms[room]["messages"], name=name)

# Event listener for incoming messages
@socketio.on("message")
def handle_message(data):
    room = session.get("room")

    # Do nothing if room is invalid
    if room not in rooms:
        return 

    # Create message object with metadata
    content = {
        "name": session.get("name"),
        "message": data["data"],
        "time": datetime.now().strftime("%H:%M:%S"),
        "is_file": data.get("isFile", False),
        "file_type": data.get("fileType", None)
    }

    # Send the message to everyone in the room
    send(content, to=room)

    # Save the message in server-side memory
    rooms[room]["messages"].append(content)

    # Print the message to server console
    print(f"{session.get('name')} sent: {data['data']}")

# Event listener when a user connects (e.g., opens the room page)
@socketio.on("connect")
def handle_connect(auth):
    room = session.get("room")
    name = session.get("name")

    # Exit early if session is invalid
    if not room or not name:
        return

    # Exit if room is invalid
    if room not in rooms:
        leave_room(room)
        return

    # Add user to the room
    join_room(room)
    rooms[room]["members"].add(name)

    # Send updated user list to everyone
    send_user_update(room)

    # Broadcast user has entered message
    send({
        "name": name,
        "message": "has entered the room",
        "time": datetime.now().strftime("%H:%M:%S"),
        "is_file": False
    }, to=room)

    # Log the event on server
    print(f"{name} joined room {room}")

# Event listener when a user disconnects (e.g., closes browser)
@socketio.on("disconnect")
def handle_disconnect():
    room = session.get("room")
    name = session.get("name")

    # If user was part of the room, remove them
    if room in rooms and name in rooms[room]["members"]:
        rooms[room]["members"].remove(name)

        # Send updated user list
        send_user_update(room)

        # Notify others in the room that user left
        send({
            "name": name,
            "message": "has left the room",
            "time": datetime.now().strftime("%H:%M:%S"),
            "is_file": False
        }, to=room)

        # Log event
        print(f"{name} has left the room {room}")

        # If no one is left in the room, delete it
        if len(rooms[room]["members"]) == 0:
            del rooms[room]

# Helper function to broadcast user list update
def send_user_update(room):
    socketio.emit("user-update", {
        "count": len(rooms[room]["members"]),
        "users": list(rooms[room]["members"])
    }, to=room)

# Run the app using SocketIO with debug mode enabled
if __name__ == "__main__":
    socketio.run(app, debug=True)
