"""
EduMind Nexus AI - Premium DeepSeek API Integration
Final Year Project - Object-Oriented Technology
"""

import os
import json
import uuid
import re
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import requests
import PyPDF2
import docx
from gtts import gTTS

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'edumind-nexus-secret-key-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///edumind.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/images', exist_ok=True)
os.makedirs('static/audio', exist_ok=True)

db = SQLAlchemy(app)


# ============================================
# DATABASE MODELS
# ============================================

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    dark_mode = db.Column(db.Boolean, default=True)


class Chat(db.Model):
    __tablename__ = 'chats'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Note(db.Model):
    __tablename__ = 'notes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Quiz(db.Model):
    __tablename__ = 'quizzes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    questions = db.Column(db.Text, nullable=False)
    score = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Flashcard(db.Model):
    __tablename__ = 'flashcards'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    topic = db.Column(db.String(255), nullable=False)
    front = db.Column(db.Text, nullable=False)
    back = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class StudyPlan(db.Model):
    __tablename__ = 'study_plans'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    plan_data = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()

# ============================================
# PREMIUM DEEPSEEK API INTEGRATION
# ✅ আপনার API Key বসানো হয়েছে
# ============================================

DEEPSEEK_API_KEY = "sk-45fa51dbb02e4778add679db15f19357"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


def call_deepseek(prompt, system_hint=None):
    """Premium DeepSeek API Call - High Quality Responses"""

    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "YOUR_PREMIUM_DEEPSEEK_API_KEY_HERE":
        return "⚠️ Please add your Premium DeepSeek API Key in the code!"

    messages = []
    if system_hint:
        messages.append({"role": "system", "content": system_hint})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000
    }

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"⚠️ API Error: {response.status_code}"
    except Exception as e:
        return f"⚠️ Connection Error: {str(e)}"


def get_ai_response(message, language='en'):
    """Get AI response from Premium DeepSeek"""
    lang_map = {'en': 'English', 'bn': 'Bangla', 'zh': 'Chinese'}
    system_prompt = f"""You are EduMind Nexus AI, a professional study assistant. 
    Reply in {lang_map.get(language, 'English')}. Be helpful, accurate, and detailed.
    Use markdown for formatting. Provide examples when helpful."""

    return call_deepseek(message, system_prompt)


def summarize_document(text, filename):
    """AI summary of uploaded document"""
    prompt = f"""Analyze this document "{filename}" and provide:
    1. Executive Summary (2-3 sentences)
    2. Key Points (5-8 bullet points)
    3. Main Topics Covered
    4. Important Terms with Definitions

    Document Content:
    {text[:4000]}"""

    return call_deepseek(prompt)


def generate_quiz(topic, num_questions=5):
    """Generate quiz using AI"""
    prompt = f"""Generate {num_questions} multiple choice questions about "{topic}".
    Return ONLY valid JSON in this exact format:
    {{"questions": [
        {{"q": "Question text here", "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"], "answer": "A) Option 1"}}
    ]}}
    Make questions educational and challenging for college students."""

    response = call_deepseek(prompt)

    # Extract JSON
    match = re.search(r'\{.*\}', response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return data.get('questions', [])
        except:
            pass

    # Fallback
    return [
        {"q": f"What is {topic}?", "options": ["A) Definition", "B) History", "C) Application", "D) All of the above"],
         "answer": "A) Definition"},
        {"q": f"Why is {topic} important?",
         "options": ["A) Reason 1", "B) Reason 2", "C) Reason 3", "D) All of the above"], "answer": "A) Reason 1"},
    ]


def generate_study_plan(subjects, days):
    """Generate study plan using AI"""
    prompt = f"""Create a comprehensive {days}-day study plan for these subjects: {subjects}.

    Please include:
    1. Daily schedule with time slots
    2. Break recommendations
    3. Revision days
    4. Study tips and techniques
    5. Progress tracking method

    Use markdown format with tables and emojis for better readability."""

    return call_deepseek(prompt)


def generate_flashcards(topic, num_cards=8):
    """Generate flashcards using AI"""
    prompt = f"""Generate {num_cards} high-quality flashcards for studying "{topic}".

    Return ONLY valid JSON in this format:
    {{"cards": [
        {{"front": "Question or term here", "back": "Answer or definition here"}}
    ]}}

    Make them educational and helpful for exam preparation."""

    response = call_deepseek(prompt)
    match = re.search(r'\{.*\}', response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return data.get('cards', [])
        except:
            pass

    return [
        {"front": f"What is {topic}?", "back": f"{topic} is an important subject to study."},
        {"front": f"Key concepts of {topic}", "back": f"There are many important concepts in {topic}."},
    ]


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf', 'docx', 'txt'}


def extract_text_from_file(filepath):
    ext = filepath.rsplit('.', 1)[1].lower()
    text = ""
    try:
        if ext == 'pdf':
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
        elif ext == 'docx':
            doc = docx.Document(filepath)
            text = '\n'.join(p.text for p in doc.paragraphs)
        elif ext == 'txt':
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
    except Exception as e:
        print(f"Error: {e}")
    return text.strip()


# ============================================
# AUTHENTICATION DECORATOR
# ============================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first!', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated


# ============================================
# ROUTES
# ============================================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password!', 'danger')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if User.query.filter_by(email=email).first():
            flash('Email already registered!', 'danger')
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.password_hash = generate_password_hash(password)
        db.session.add(user)
        db.session.commit()

        flash('Account created! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    uid = session['user_id']
    total_chats = Chat.query.filter_by(user_id=uid).count()
    total_notes = Note.query.filter_by(user_id=uid).count()
    total_quizzes = Quiz.query.filter_by(user_id=uid).count()
    total_flashcards = Flashcard.query.filter_by(user_id=uid).count()
    recent_chats = Chat.query.filter_by(user_id=uid).order_by(Chat.created_at.desc()).limit(5).all()

    return render_template('dashboard.html',
                           total_chats=total_chats,
                           total_notes=total_notes,
                           total_quizzes=total_quizzes,
                           total_flashcards=total_flashcards,
                           recent_chats=recent_chats)


@app.route('/chat')
@login_required
def chat():
    history = Chat.query.filter_by(user_id=session['user_id']).order_by(Chat.created_at).all()
    return render_template('chat.html', history=history)


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    data = request.get_json()
    message = data.get('message', '').strip()
    language = data.get('language', 'en')

    if not message:
        return jsonify({'error': 'Empty message'}), 400

    response = get_ai_response(message, language)

    uid = session['user_id']
    db.session.add(Chat(user_id=uid, role='user', content=message))
    db.session.add(Chat(user_id=uid, role='assistant', content=response))
    db.session.commit()

    return jsonify({'reply': response})


@app.route('/api/clear_chat', methods=['POST'])
@login_required
def clear_chat():
    Chat.query.filter_by(user_id=session['user_id']).delete()
    db.session.commit()
    return jsonify({'success': True})


@app.route('/notes', methods=['GET', 'POST'])
@login_required
def notes():
    uid = session['user_id']

    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash('No file selected!', 'danger')
            return redirect(url_for('notes'))

        if not allowed_file(file.filename):
            flash('Only PDF, DOCX, TXT files allowed!', 'danger')
            return redirect(url_for('notes'))

        filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        file.save(filepath)

        text = extract_text_from_file(filepath)
        if text:
            summary = summarize_document(text, filename)
            flash('File uploaded and summarized!', 'success')
        else:
            summary = 'Could not extract text from this file.'
            flash('Could not extract text!', 'warning')

        note = Note(user_id=uid, filename=unique_name, original_name=filename, summary=summary)
        db.session.add(note)
        db.session.commit()

        return redirect(url_for('notes'))

    notes = Note.query.filter_by(user_id=uid).order_by(Note.created_at.desc()).all()
    return render_template('notes.html', notes=notes)


@app.route('/notes/<int:note_id>')
@login_required
def view_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != session['user_id']:
        return redirect(url_for('notes'))
    return render_template('note_detail.html', note=note)


@app.route('/notes/<int:note_id>/delete', methods=['POST'])
@login_required
def delete_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id == session['user_id']:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], note.filename))
        except:
            pass
        db.session.delete(note)
        db.session.commit()
        flash('Note deleted!', 'success')
    return redirect(url_for('notes'))


@app.route('/quiz', methods=['GET', 'POST'])
@login_required
def quiz():
    uid = session['user_id']

    if request.method == 'POST':
        topic = request.form.get('topic', '').strip()
        if not topic:
            flash('Please enter a topic!', 'danger')
            return redirect(url_for('quiz'))

        questions = generate_quiz(topic)

        if questions:
            quiz = Quiz(user_id=uid, title=topic, questions=json.dumps(questions), total=len(questions))
            db.session.add(quiz)
            db.session.commit()
            session['current_quiz'] = quiz.id
            return redirect(url_for('take_quiz', quiz_id=quiz.id))
        else:
            flash('Could not generate quiz. Try another topic!', 'warning')

    quizzes = Quiz.query.filter_by(user_id=uid).order_by(Quiz.created_at.desc()).all()
    return render_template('quiz.html', quizzes=quizzes)


@app.route('/quiz/take/<int:quiz_id>')
@login_required
def take_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    if quiz.user_id != session['user_id']:
        return redirect(url_for('quiz'))

    questions = json.loads(quiz.questions)
    return render_template('take_quiz.html', quiz=quiz, questions=questions)


@app.route('/api/quiz/submit/<int:quiz_id>', methods=['POST'])
@login_required
def submit_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    if quiz.user_id != session['user_id']:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    answers = data.get('answers', {})
    questions = json.loads(quiz.questions)

    score = 0
    for i, q in enumerate(questions):
        user_answer = answers.get(str(i), '').strip()
        correct = q.get('answer', '').strip()
        if user_answer.lower() == correct.lower():
            score += 1

    quiz.score = score
    db.session.commit()

    return jsonify({'score': score, 'total': len(questions), 'percentage': (score / len(questions)) * 100})


@app.route('/planner', methods=['GET', 'POST'])
@login_required
def planner():
    plan = None
    if request.method == 'POST':
        subjects = request.form.get('subjects', '')
        days = request.form.get('days', '7')

        if subjects:
            plan = generate_study_plan(subjects, days)
            study_plan = StudyPlan(user_id=session['user_id'], title=f"Study Plan: {subjects[:50]}", plan_data=plan)
            db.session.add(study_plan)
            db.session.commit()

    study_plans = StudyPlan.query.filter_by(user_id=session['user_id']).order_by(StudyPlan.created_at.desc()).limit(
        5).all()
    return render_template('planner.html', plan=plan, study_plans=study_plans)


@app.route('/flashcards', methods=['GET', 'POST'])
@login_required
def flashcards():
    cards = []
    if request.method == 'POST':
        topic = request.form.get('topic', '').strip()
        if topic:
            cards = generate_flashcards(topic)
            for card in cards:
                flashcard = Flashcard(user_id=session['user_id'], topic=topic, front=card.get('front', ''),
                                      back=card.get('back', ''))
                db.session.add(flashcard)
            db.session.commit()

    saved_cards = Flashcard.query.filter_by(user_id=session['user_id']).order_by(Flashcard.created_at.desc()).limit(
        20).all()
    return render_template('flashcards.html', cards=cards, saved_cards=saved_cards)


@app.route('/api/tts', methods=['POST'])
@login_required
def text_to_speech():
    data = request.get_json()
    text = data.get('text', '').strip()
    lang = data.get('lang', 'en')

    if not text:
        return jsonify({'error': 'Empty text'}), 400

    lang_map = {'en': 'en', 'bn': 'bn', 'zh': 'zh-CN'}
    try:
        tts = gTTS(text=text[:500], lang=lang_map.get(lang, 'en'))
        filename = f"tts_{uuid.uuid4().hex[:10]}.mp3"
        filepath = os.path.join('static/audio', filename)
        tts.save(filepath)
        return jsonify({'audio_url': f'/static/audio/{filename}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        dark_mode = request.form.get('dark_mode') == 'on'
        user.dark_mode = dark_mode
        db.session.commit()
        flash('Settings updated!', 'success')

    return render_template('settings.html', user=user)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)