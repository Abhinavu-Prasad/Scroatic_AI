import os
import json
import sqlite3
import time
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import re
from transformers import pipeline, AutoModelForCausalLM, AutoTokenizer
import torch
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-default-key")

# ==========================================
# 1. DATABASE SETUP
# ==========================================
def setup_database():
    conn = sqlite3.connect('tutor_memory.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            tries_left INTEGER DEFAULT 5,
            last_concept TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    return conn

db = setup_database()

# ==========================================
# 2. LOCAL AI CONFIGURATION
# ==========================================

print("[SYSTEM]: Initializing Local AI Model. This may take a few minutes if downloading...")
MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
try:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, 
        torch_dtype="auto", 
        device_map="auto"
    )
    pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)
    print("[SYSTEM]: Local AI Model loaded successfully!")
except Exception as e:
    print(f"[SYSTEM]: Error loading model: {e}")
    pipe = None

SYSTEM_PROMPT = """
You are the 'Socratic Gatekeeper', a strict and highly accurate AI tutor.
You must follow this exact conversation flow:

1. INITIAL PROMPT: When the user asks a question, ask EXACTLY ONE question ON THAT SPECIFIC TOPIC to test their current understanding before giving the result. You must gauge their knowledge of the topic first. Do not give the answer yet.
2. CORRECT ANSWER: If they answer your test correctly (or show partial knowledge), give them the FULL, highly accurate, and comprehensive answer to their original question. Output the topic in "new_concept_learned".
3. NEW PROMPTS (THE GATEKEEPER): If the user asks a NEW question later in the chat, STOP. You must ask them one review question about the PREVIOUS topic you just taught them. Do not answer the new question until they pass the review of the old topic.
4. INCORRECT ANSWERS: If they get any test or review question wrong, set "deduct_try" to true, briefly correct them, and ask a slightly different/easier question to test them again.

Your output MUST be a strict JSON object with exactly these five keys:
1. "internal_thoughts": Your reasoning for the current step.
2. "tutor_reply": Your message to the user.
3. "is_correct": true ONLY if they just answered a test correctly.
4. "deduct_try": true ONLY if they gave a wrong answer.
5. "new_concept_learned": The topic name IF you just gave a full answer, otherwise null.

OUTPUT ONLY JSON AND NOTHING ELSE. DO NOT WRAP IN MARKDOWN.
"""

def get_chat_history(user_id):
    cursor = db.cursor()
    cursor.execute('SELECT sender, message FROM chat_history WHERE user_id=? ORDER BY timestamp ASC', (user_id,))
    rows = cursor.fetchall()
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for sender, msg in rows:
        role = "user" if sender == "user" else "assistant"
        messages.append({"role": role, "content": msg})
    return messages

def extract_json(text):
    match = re.search(r'```(?:json)?(.*?)```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != 0:
            return json.loads(text[start:end])
    except:
        pass
    raise ValueError("Failed to extract valid JSON.")

def send_message_with_retry(user_id, prompt_text, max_retries=3):
    messages = get_chat_history(user_id)
    messages.append({"role": "user", "content": prompt_text})
    
    if pipe is None:
        raise Exception("Local AI model failed to load. Check logs.")
        
    for attempt in range(max_retries):
        try:
            outputs = pipe(
                messages,
                max_new_tokens=500,
                temperature=0.1,
                do_sample=True,
                return_full_text=False
            )
            response_text = outputs[0]["generated_text"].strip()
            return extract_json(response_text)
        except Exception as e:
            print(f"[SYSTEM]: Local model error ({e}). Retrying... (Attempt {attempt+1}/{max_retries})")
            time.sleep(1)
            
    return {
        "internal_thoughts": "The local model struggled to format its output as JSON.",
        "tutor_reply": "I'm having a little trouble processing right now. Can you ask that in a slightly different way?",
        "is_correct": False,
        "deduct_try": False,
        "new_concept_learned": None
    }

# ==========================================
# 3. FLASK ENDPOINTS
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=session.get('username'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        cursor = db.cursor()
        cursor.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            return redirect(url_for('index'))
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            return render_template('register.html', error='Username and password required')
            
        cursor = db.cursor()
        try:
            cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                         (username, generate_password_hash(password)))
            db.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return render_template('register.html', error='Username already exists')
            
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/state', methods=['GET'])
@login_required
def get_state():
    user_id = session['user_id']
    cursor = db.cursor()
    cursor.execute('SELECT tries_left, last_concept FROM users WHERE id=?', (user_id,))
    tries_left, last_concept = cursor.fetchone()
    
    cursor.execute('SELECT sender, message FROM chat_history WHERE user_id=? ORDER BY timestamp ASC', (user_id,))
    history = [{"sender": row[0], "message": row[1]} for row in cursor.fetchall()]
    
    initial_message = None
    if not history:
        if last_concept:
            gatekeeper_prompt = f"The user is returning. Generate a quick quiz question testing their knowledge on their last learned concept: '{last_concept}'. Do not let them change the subject until they answer it."
            try:
                ai_data = send_message_with_retry(user_id, gatekeeper_prompt)
                initial_message = ai_data.get('tutor_reply')
                cursor.execute('INSERT INTO chat_history (user_id, sender, message) VALUES (?, ?, ?)', (user_id, 'tutor', initial_message))
                db.commit()
            except Exception as e:
                print(f"[System Error during bootup]: {e}")
                initial_message = "Welcome back! I encountered a small glitch, but I'm ready to continue our lessons."

    return jsonify({
        "tries_left": tries_left,
        "last_concept": last_concept,
        "initial_message": initial_message,
        "history": history
    })

@app.route('/api/chat', methods=['POST'])
@login_required
def chat_endpoint():
    data = request.json
    user_message = data.get('message', '')
    user_id = session['user_id']
    
    cursor = db.cursor()
    cursor.execute('SELECT tries_left FROM users WHERE id=?', (user_id,))
    tries_left = cursor.fetchone()[0]

    if tries_left <= 0:
        return jsonify({
            "tutor_reply": "You are out of tries for today! You need to study offline. Goodbye.",
            "deduct_try": False,
            "tries_left": 0,
            "new_concept_learned": None
        })
        
    try:
        cursor.execute('INSERT INTO chat_history (user_id, sender, message) VALUES (?, ?, ?)', (user_id, 'user', user_message))
        db.commit()

        ai_data = send_message_with_retry(user_id, user_message)
        
        cursor.execute('INSERT INTO chat_history (user_id, sender, message) VALUES (?, ?, ?)', (user_id, 'tutor', ai_data.get('tutor_reply', '')))
        db.commit()
        
        if ai_data.get("deduct_try"):
            tries_left -= 1
            cursor.execute('UPDATE users SET tries_left = ? WHERE id = ?', (tries_left, user_id))
            db.commit()
            
        new_concept = ai_data.get("new_concept_learned")
        if new_concept:
            cursor.execute('UPDATE users SET last_concept = ? WHERE id = ?', (new_concept, user_id))
            db.commit()
            
        ai_data["tries_left"] = tries_left
        return jsonify(ai_data)
        
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

@app.route('/api/reset', methods=['POST'])
@login_required
def reset_tries():
    user_id = session['user_id']
    cursor = db.cursor()
    cursor.execute('UPDATE users SET tries_left = 5 WHERE id = ?', (user_id,))
    db.commit()
    return jsonify({"success": True, "tries_left": 5})

if __name__ == "__main__":
    app.run(debug=True, port=5000)