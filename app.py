from flask import Flask, render_template, request, redirect, session, jsonify
from flask_socketio import SocketIO, emit, join_room
import psycopg2, os, bcrypt, uuid

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","secret")

socketio = SocketIO(app, cors_allowed_origins="*")

# ===== DB =====
def db():
    return psycopg2.connect(os.environ.get("DATABASE_URL"))

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        password TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS friends(
        user1 TEXT,
        user2 TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        id SERIAL PRIMARY KEY,
        user1 TEXT,
        user2 TEXT,
        text TEXT,
        image TEXT
    )
    """)

    con.commit()
    con.close()

init_db()

# ===== AUTH =====
@app.route('/')
def home():
    if 'user' in session:
        return redirect('/chat')
    return render_template("login.html")

@app.route('/chat')
def chat():
    if 'user' not in session:
        return redirect('/')
    return render_template("chat.html", user=session['user'])

@app.route('/register', methods=['POST'])
def register():
    u = request.form['username']
    p = request.form['password']

    hashed = bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

    con = db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO users VALUES (%s,%s)", (u,hashed))
        con.commit()
    except:
        return "User tồn tại"
    return "OK"

@app.route('/login', methods=['POST'])
def login():
    u = request.form['username']
    p = request.form['password']

    con = db(); cur = con.cursor()
    cur.execute("SELECT password FROM users WHERE username=%s",(u,))
    row = cur.fetchone()

    if row and bcrypt.checkpw(p.encode(), row[0].encode()):
        session['user'] = u
        return "OK"

    return "Sai tài khoản"

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ===== FRIEND =====
@app.route('/add_friend', methods=['POST'])
def add_friend():
    f = session['user']
    t = request.form['to']

    con = db(); cur = con.cursor()
    cur.execute("INSERT INTO friends VALUES (%s,%s)", (f,t))
    cur.execute("INSERT INTO friends VALUES (%s,%s)", (t,f))
    con.commit()

    return "OK"

@app.route('/friends')
def friends():
    u = session['user']
    con = db(); cur = con.cursor()

    cur.execute("SELECT user2 FROM friends WHERE user1=%s",(u,))
    data = [x[0] for x in cur.fetchall()]
    return jsonify(data)

# ===== UPLOAD =====
@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    name = str(uuid.uuid4()) + ".png"
    path = "static/uploads/" + name
    file.save(path)
    return "/" + path

# ===== MESSAGES =====
@app.route('/messages/<user>')
def messages(user):
    me = session['user']
    con = db(); cur = con.cursor()

    cur.execute("""
    SELECT user1,text,image FROM messages
    WHERE (user1=%s AND user2=%s) OR (user1=%s AND user2=%s)
    """,(me,user,user,me))

    return jsonify([
        {"user":r[0],"text":r[1],"image":r[2]}
        for r in cur.fetchall()
    ])

# ===== SOCKET =====
@socketio.on("join")
def join(data):
    room = "_".join(sorted([data['u1'], data['u2']]))
    join_room(room)

@socketio.on("send")
def send(data):
    u1 = session['user']
    u2 = data['to']
    text = data.get("text","")
    image = data.get("image","")

    room = "_".join(sorted([u1,u2]))

    con = db(); cur = con.cursor()
    cur.execute(
        "INSERT INTO messages(user1,user2,text,image) VALUES (%s,%s,%s,%s)",
        (u1,u2,text,image)
    )
    con.commit()

    emit("msg", {
        "user":u1,
        "text":text,
        "image":image
    }, to=room)

# ===== RUN =====
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
