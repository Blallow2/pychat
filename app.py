from flask import Flask, render_template, request, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room
import sqlite3
import datetime
import os

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# ===== DB =====
def get_db():
    return sqlite3.connect("chat.db", check_same_thread=False)

# ===== INIT DB =====
db = get_db()
c = db.cursor()

c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS friends (user1 TEXT, user2 TEXT, UNIQUE(user1,user2))")
c.execute("CREATE TABLE IF NOT EXISTS requests (from_user TEXT, to_user TEXT, UNIQUE(from_user,to_user))")
c.execute("CREATE TABLE IF NOT EXISTS messages (user TEXT, text TEXT, room TEXT)")

db.commit()
db.close()

# ===== ONLINE =====
online_users = set()
user_map = {}

# ===== ROUTES =====
@app.route('/')
def home():
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    db = get_db()
    c = db.cursor()

    try:
        c.execute("INSERT INTO users VALUES (?,?)",
                  (request.form['username'], request.form['password']))
        db.commit()
    except:
        db.close()
        return "User đã tồn tại"

    db.close()
    return redirect('/')

@app.route('/login', methods=['POST'])
def login():
    db = get_db()
    c = db.cursor()

    u = request.form['username']
    p = request.form['password']

    c.execute("SELECT * FROM users WHERE username=? AND password=?", (u,p))
    if c.fetchone():
        db.close()
        return redirect(f"/chat/{u}")

    db.close()
    return "Sai tài khoản"

@app.route('/chat/<user>')
def chat(user):
    return render_template('chat.html', user=user)

# ===== FRIEND =====
@app.route('/add_friend', methods=['POST'])
def add_friend():
    db = get_db()
    c = db.cursor()

    f = request.form['from']
    t = request.form['to']

    if f == t:
        return "Không thể tự kết bạn"

    c.execute("SELECT * FROM users WHERE username=?", (t,))
    if not c.fetchone():
        return "User không tồn tại"

    c.execute("SELECT * FROM friends WHERE user1=? AND user2=?", (f,t))
    if c.fetchone():
        return "Đã là bạn"

    c.execute("SELECT * FROM requests WHERE from_user=? AND to_user=?", (f,t))
    if c.fetchone():
        return "Đã gửi rồi"

    # auto accept
    c.execute("SELECT * FROM requests WHERE from_user=? AND to_user=?", (t,f))
    if c.fetchone():
        c.execute("INSERT OR IGNORE INTO friends VALUES (?,?)", (f,t))
        c.execute("INSERT OR IGNORE INTO friends VALUES (?,?)", (t,f))
        c.execute("DELETE FROM requests WHERE from_user=? AND to_user=?", (t,f))
        db.commit()
        db.close()
        return "Đã kết bạn"

    c.execute("INSERT OR IGNORE INTO requests VALUES (?,?)", (f,t))
    db.commit()
    db.close()
    return "OK"

@app.route('/accept', methods=['POST'])
def accept():
    db = get_db()
    c = db.cursor()

    u1 = request.form['from']
    u2 = request.form['to']

    c.execute("INSERT OR IGNORE INTO friends VALUES (?,?)", (u1,u2))
    c.execute("INSERT OR IGNORE INTO friends VALUES (?,?)", (u2,u1))
    c.execute("DELETE FROM requests WHERE from_user=? AND to_user=?", (u1,u2))

    db.commit()
    db.close()
    return "OK"

@app.route('/friends/<user>')
def friends(user):
    db = get_db()
    c = db.cursor()

    c.execute("SELECT user2 FROM friends WHERE user1=?", (user,))
    data = [f[0] for f in c.fetchall()]

    db.close()
    return jsonify({"friends": data})

@app.route('/requests/<user>')
def get_requests(user):
    db = get_db()
    c = db.cursor()

    c.execute("SELECT from_user FROM requests WHERE to_user=?", (user,))
    data = [r[0] for r in c.fetchall()]

    db.close()
    return jsonify({"requests": data})

@app.route('/messages/<room>')
def messages(room):
    db = get_db()
    c = db.cursor()

    c.execute("SELECT user,text FROM messages WHERE room=?", (room,))
    data = [{"user":r[0],"text":r[1]} for r in c.fetchall()]

    db.close()
    return jsonify(data)

# ===== PYTHON BOT =====
def handle_python(cmd):
    try:
        parts = cmd.split()

        if not parts:
            return "Không có lệnh"

        if parts[0] == "add":
            return str(sum(map(int, parts[1:])))
        elif parts[0] == "mul":
            result = 1
            for n in map(int, parts[1:]):
                result *= n
            return str(result)
        elif parts[0] == "time":
            return str(datetime.datetime.now())
        elif parts[0] == "help":
            return "add | mul | time"

        return "Sai lệnh"
    except:
        return "Lỗi command"

# ===== SOCKET =====
@socketio.on("join")
def join(data):
    user = data['user']
    room = data['room']

    join_room(room)

    user_map[request.sid] = user
    online_users.add(user)

    emit("online_list", list(online_users), broadcast=True)

@socketio.on("disconnect")
def disconnect():
    user = user_map.get(request.sid)

    if user:
        online_users.discard(user)
        user_map.pop(request.sid, None)

    emit("online_list", list(online_users), broadcast=True)

@socketio.on("send_message")
def msg(data):
    user = data['user']
    text = data['text']
    room = data['room']

    # 🤖 BOT
    if text.startswith("/py"):
        result = handle_python(text[4:])

        emit("receive_message", {
            "user": "🤖 PyBot",
            "text": result,
            "room": room
        }, to=room)
        return

    # 💾 SAVE MESSAGE
    db = get_db()
    c = db.cursor()

    c.execute("INSERT INTO messages VALUES (?,?,?)",
              (user, text, room))

    db.commit()
    db.close()

    emit("receive_message", data, to=room)

# ===== RUN (DEPLOY READY) =====
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)