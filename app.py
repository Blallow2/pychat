from flask import Flask, render_template, request, redirect, jsonify, session
from flask_socketio import SocketIO, emit, join_room
import sqlite3
import os
import io
import contextlib
import signal

app = Flask(__name__)
app.secret_key = "pychat_secret"

socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# ===== DATABASE =====
def get_db():
    return sqlite3.connect("chat.db", check_same_thread=False)

def init_db():
    db = get_db()
    c = db.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT UNIQUE,
        password TEXT,
        email TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS friends(
        user1 TEXT,
        user2 TEXT,
        UNIQUE(user1,user2)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        user TEXT,
        text TEXT,
        room TEXT
    )
    """)

    db.commit()
    db.close()

init_db()

# ===== ONLINE =====
online_users = set()
user_map = {}

# ===== ROUTES =====
@app.route('/')
def home():
    if 'user' in session:
        return redirect('/chat')
    return render_template('login.html')

@app.route('/chat')
def chat():
    if 'user' not in session:
        return redirect('/')
    return render_template('chat.html', user=session['user'])

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')

# ===== LOGIN =====
@app.route('/login', methods=['POST'])
def login():
    db = get_db()
    c = db.cursor()

    u = request.form['username']
    p = request.form['password']

    c.execute("SELECT * FROM users WHERE username=? AND password=?", (u,p))
    if c.fetchone():
        session['user'] = u
        db.close()
        return redirect('/chat')

    db.close()
    return "Sai tài khoản"

# ===== REGISTER =====
@app.route('/register', methods=['POST'])
def register():
    db = get_db()
    c = db.cursor()

    u = request.form['username']
    p = request.form['password']
    e = request.form['email']

    try:
        c.execute("INSERT INTO users VALUES (?,?,?)", (u,p,e))
        db.commit()
    except:
        db.close()
        return "User tồn tại"

    db.close()
    return "OK"

# ===== FRIEND =====
@app.route('/add_friend', methods=['POST'])
def add_friend():
    db = get_db()
    c = db.cursor()

    f = request.form['from']
    t = request.form['to']

    if f == t:
        return "Không thể tự kết bạn"

    c.execute("SELECT * FROM friends WHERE user1=? AND user2=?", (f,t))
    if c.fetchone():
        return "Đã là bạn"

    c.execute("INSERT OR IGNORE INTO friends VALUES (?,?)", (f,t))
    c.execute("INSERT OR IGNORE INTO friends VALUES (?,?)", (t,f))

    db.commit()
    db.close()
    return "OK"

@app.route('/friends/<user>')
def friends(user):
    db = get_db()
    c = db.cursor()

    c.execute("SELECT user2 FROM friends WHERE user1=?", (user,))
    data = [x[0] for x in c.fetchall()]

    db.close()
    return jsonify(data)

# ===== MESSAGES =====
@app.route('/messages/<room>')
def messages(room):
    db = get_db()
    c = db.cursor()

    c.execute("SELECT user,text FROM messages WHERE room=?", (room,))
    data = [{"user":r[0],"text":r[1]} for r in c.fetchall()]

    db.close()
    return jsonify(data)

# ===== PYTHON IDE BOT =====
SAFE_BUILTINS = {
    "print": print,
    "len": len,
    "sum": sum,
    "range": range,
    "int": int,
    "float": float,
    "str": str
}

def is_safe(code):
    banned = ["import", "os", "sys", "open", "__", "eval", "exec"]
    return not any(x in code for x in banned)

class TimeoutException(Exception):
    pass

def handler(signum, frame):
    raise TimeoutException()

signal.signal(signal.SIGALRM, handler)

def run_code(code):
    if not is_safe(code):
        return "❌ Code không an toàn"

    output = io.StringIO()

    try:
        signal.alarm(2)
        with contextlib.redirect_stdout(output):
            exec(code, {"__builtins__": SAFE_BUILTINS}, {})
        signal.alarm(0)
    except TimeoutException:
        return "⏱️ Quá thời gian"
    except Exception as e:
        return f"❌ Lỗi: {e}"

    return output.getvalue() or "✅ OK"

# ===== SOCKET =====
@socketio.on("join")
def join(data):
    user = data['user']
    room = data['room']

    join_room(room)
    user_map[request.sid] = user
    online_users.add(user)

    emit("online", list(online_users), broadcast=True)

@socketio.on("disconnect")
def disconnect():
    user = user_map.get(request.sid)
    if user:
        online_users.discard(user)
        user_map.pop(request.sid, None)

    emit("online", list(online_users), broadcast=True)

@socketio.on("send_message")
def handle_msg(data):
    user = data['user']
    text = data['text']
    room = data['room']

    # 🤖 IDE BOT
    if text.startswith("/py"):
        result = run_code(text[3:].strip())
        emit("receive_message", {
            "user": "🤖 PyIDE",
            "text": result
        }, to=room)
        return

    # 💾 SAVE
    db = get_db()
    c = db.cursor()

    c.execute("INSERT INTO messages VALUES (?,?,?)", (user,text,room))
    db.commit()
    db.close()

    emit("receive_message", data, to=room)

# ===== RUN =====
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
