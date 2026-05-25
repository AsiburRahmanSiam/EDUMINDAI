"""
EduMind Nexus AI - Complete Version with All Features
Deployment Ready for Render.com with PostgreSQL Support
"""

import os
import json
import uuid
import re
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import requests
import PyPDF2
import docx
from gtts import gTTS
from io import BytesIO

# Try to import weasyprint, but don't fail if not available
try:
    import weasyprint
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    print("WeasyPrint not available, PDF export disabled")

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'edumind-nexus-secret-key-2026')

# PostgreSQL support - Use DATABASE_URL from Render, fallback to SQLite for local development
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///edumind.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# Create directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/images', exist_ok=True)
os.makedirs('static/audio', exist_ok=True)
os.makedirs('static/uploads', exist_ok=True)

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
    study_streak = db.Column(db.Integer, default=0)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    reset_token = db.Column(db.String(100), nullable=True)


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
    shared = db.Column(db.Boolean, default=False)


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


# ============================================
# UPDATE STUDY STREAK DECORATOR
# ============================================

def update_study_streak(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user:
                today = datetime.utcnow().date()
                last = user.last_active.date() if user.last_active else None
                if last == today - timedelta(days=1):
                    user.study_streak += 1
                elif last != today:
                    user.study_streak = 1
                user.last_active = datetime.utcnow()
                db.session.commit()
                session['study_streak'] = user.study_streak
        return f(*args, **kwargs)

    return decorated


# ============================================
# DEEPSEEK API INTEGRATION
# ============================================

DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-45fa51dbb02e4778add679db15f19357')
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


def call_deepseek(prompt, system_hint=None):
    """Call DeepSeek API with fallback"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == 'your-deepseek-api-key-here':
        return get_fallback_response(prompt)

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
            return get_fallback_response(prompt)
    except Exception as e:
        return get_fallback_response(prompt)


def get_fallback_response(prompt):
    """Fallback responses when API is unavailable"""
    prompt_lower = prompt.lower()

    if 'python' in prompt_lower:
        return """**Python** is a high-level, interpreted programming language created by Guido van Rossum in 1991.

**Key Features:**
1. Easy to learn syntax
2. Dynamically typed
3. Extensive libraries (NumPy, Pandas, TensorFlow)
4. Object-oriented programming
5. Cross-platform compatibility

**Example:**
```python
print('Hello, World!')
```"""

    elif 'machine learning' in prompt_lower or 'ml' in prompt_lower:
        return """**Machine Learning (ML)** is a subset of Artificial Intelligence that enables systems to learn from data.

**Main Types:**
1. **Supervised Learning** - Learning from labeled data
2. **Unsupervised Learning** - Finding patterns in unlabeled data
3. **Reinforcement Learning** - Learning through rewards

**Applications:**
- Spam detection
- Image recognition
- Recommendation systems
- Self-driving cars"""

    elif 'zhengzhou university' in prompt_lower:
        return """**Zhengzhou University (郑州大学)** is a prestigious public university in Zhengzhou, Henan, China.

**Key Information:**
- **Founded:** 1956
- **Type:** Public research university
- **Students:** 70,000+
- **Ranking:** Among top 100 universities in China
- **Member of Project 211**

**Notable Programs:**
- Medicine
- Engineering
- Materials Science
- Chemistry"""

    else:
        return """I'm EduMind Nexus AI, your intelligent study assistant! 📚

**I can help you with:**
- Programming (Python, JavaScript, Flask)
- Data Science & Machine Learning
- Science, Mathematics, History
- Exam preparation & study techniques
- Career guidance & interviews

**Try asking me:**
- "What is Python?"
- "Explain machine learning"
- "What is Zhengzhou University?"
- "How to study effectively?"

How can I help you today? 🚀"""


def get_ai_response(message, language='en'):
    """Get AI response"""
    lang_map = {'en': 'English', 'bn': 'Bangla', 'zh': 'Chinese'}
    system_prompt = f"You are EduMind Nexus AI, a professional study assistant. Reply in {lang_map.get(language, 'English')}. Be helpful and detailed."
    return call_deepseek(message, system_prompt)


def summarize_document(text, filename):
    """Summarize document using AI"""
    prompt = f"""Analyze this document "{filename}" and provide:
    1. Executive Summary
    2. Key Points (5-8 bullet points)
    3. Main Topics Covered

    Content: {text[:4000]}"""
    return call_deepseek(prompt)


def generate_quiz(topic, num_questions=5):
    """Generate quiz using AI"""
    prompt = f"""Generate {num_questions} multiple choice questions about "{topic}".
    Return ONLY valid JSON in this format:
    {{"questions": [
        {{"q": "Question text", "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"], "answer": "A) Option 1"}}
    ]}}"""

    response = call_deepseek(prompt)
    match = re.search(r'\{.*\}', response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group()).get('questions', [])
        except:
            pass

    # Fallback questions
    return [
        {"q": f"What is {topic}?", "options": ["A) Definition", "B) History", "C) Application", "D) All of the above"],
         "answer": "A) Definition"},
        {"q": f"Why is {topic} important?",
         "options": ["A) Reason 1", "B) Reason 2", "C) Reason 3", "D) All of the above"], "answer": "A) Reason 1"},
        {"q": f"Key concept in {topic}", "options": ["A) Concept A", "B) Concept B", "C) Concept C", "D) Concept D"],
         "answer": "A) Concept A"},
        {"q": f"Application of {topic}",
         "options": ["A) Application 1", "B) Application 2", "C) Application 3", "D) Application 4"],
         "answer": "A) Application 1"},
        {"q": f"Future of {topic}",
         "options": ["A) Future trend 1", "B) Future trend 2", "C) Future trend 3", "D) Future trend 4"],
         "answer": "A) Future trend 1"}
    ][:num_questions]


def generate_study_plan(subjects, days):
    """Generate study plan using AI"""
    prompt = f"""Create a comprehensive {days}-day study plan for these subjects: {subjects}.

    Include:
    1. Daily schedule with time slots
    2. Break recommendations
    3. Revision days
    4. Study tips

    Use markdown format with emojis."""
    return call_deepseek(prompt)


def generate_flashcards(topic, num_cards=8):
    """Generate flashcards using AI"""
    prompt = f"""Generate {num_cards} flashcards for studying "{topic}".

    Return ONLY JSON in this format:
    {{"cards": [
        {{"front": "Question/term", "back": "Answer/definition"}}
    ]}}"""

    response = call_deepseek(prompt)
    match = re.search(r'\{.*\}', response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group()).get('cards', [])
        except:
            pass

    # Fallback flashcards
    return [
        {"front": f"What is {topic}?", "back": f"{topic} is an important subject to study."},
        {"front": f"Key concepts of {topic}", "back": f"There are many important concepts in {topic}."},
        {"front": f"Applications of {topic}", "back": f"{topic} has many real-world applications."},
        {"front": f"Why study {topic}?", "back": f"Understanding {topic} opens many career opportunities."},
    ][:num_cards]


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
        print(f"Error extracting text: {e}")
    return text.strip()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first!', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated


# ============================================
# AUTHENTICATION ROUTES
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
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            session['dark_mode'] = user.dark_mode
            session['study_streak'] = user.study_streak
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


@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    user = User.query.get(session['user_id'])
    if user:
        Chat.query.filter_by(user_id=user.id).delete()
        Note.query.filter_by(user_id=user.id).delete()
        Quiz.query.filter_by(user_id=user.id).delete()
        Flashcard.query.filter_by(user_id=user.id).delete()
        StudyPlan.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
        session.clear()
        flash('Account deleted successfully!', 'success')
    return redirect(url_for('login'))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = str(uuid.uuid4())
            user.reset_token = token
            db.session.commit()
            flash(f'Password reset link: /reset_password/{token}', 'info')
        else:
            flash('Email not found!', 'danger')
    return render_template('forgot_password.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    if not user:
        flash('Invalid or expired token!', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        password = request.form.get('password')
        user.password_hash = generate_password_hash(password)
        user.reset_token = None
        db.session.commit()
        flash('Password reset successfully! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html')


@app.route('/toggle_theme')
@login_required
def toggle_theme():
    user = User.query.get(session['user_id'])
    if user:
        user.dark_mode = not user.dark_mode
        db.session.commit()
        session['dark_mode'] = user.dark_mode
    return redirect(request.referrer or url_for('dashboard'))


# ============================================
# MAIN ROUTES
# ============================================

@app.route('/dashboard')
@login_required
@update_study_streak
def dashboard():
    uid = session['user_id']
    total_chats = Chat.query.filter_by(user_id=uid).count()
    total_notes = Note.query.filter_by(user_id=uid).count()
    total_quizzes = Quiz.query.filter_by(user_id=uid).count()
    total_flashcards = Flashcard.query.filter_by(user_id=uid).count()

    # Quiz data for chart
    quizzes = Quiz.query.filter_by(user_id=uid).all()
    quiz_labels = [q.title[:15] for q in quizzes[-5:]]
    quiz_percentages = [(q.score / q.total * 100) if q.total > 0 else 0 for q in quizzes[-5:]]

    return render_template('dashboard.html',
                           total_chats=total_chats,
                           total_notes=total_notes,
                           total_quizzes=total_quizzes,
                           total_flashcards=total_flashcards,
                           quiz_labels=quiz_labels,
                           quiz_percentages=quiz_percentages)


@app.route('/chat')
@login_required
@update_study_streak
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
@update_study_streak
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

    search = request.args.get('search', '')
    if search:
        notes = Note.query.filter_by(user_id=uid).filter(Note.original_name.contains(search)).order_by(
            Note.created_at.desc()).all()
    else:
        notes = Note.query.filter_by(user_id=uid).order_by(Note.created_at.desc()).all()

    return render_template('notes.html', notes=notes, search=search)


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


@app.route('/notes/<int:note_id>/export_pdf')
@login_required
def export_note_pdf(note_id):
    if not WEASYPRINT_AVAILABLE:
        flash('PDF export is not available on this server.', 'warning')
        return redirect(url_for('view_note', note_id=note_id))

    note = Note.query.get_or_404(note_id)
    if note.user_id != session['user_id']:
        return redirect(url_for('notes'))

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>{note.original_name}</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 40px; }}
            h1 {{ color: #7c3aed; }}
            .summary {{ line-height: 1.6; }}
        </style>
    </head>
    <body>
        <h1>{note.original_name}</h1>
        <p><small>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}</small></p>
        <div class="summary">{note.summary | safe}</div>
    </body>
    </html>
    """
    pdf = weasyprint.HTML(string=html_content).write_pdf()
    return send_file(BytesIO(pdf), download_name=f"{note.original_name}.pdf", as_attachment=True)


@app.route('/quiz', methods=['GET', 'POST'])
@login_required
@update_study_streak
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


@app.route('/api/quiz/share/<int:quiz_id>', methods=['POST'])
@login_required
def share_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    if quiz.user_id != session['user_id']:
        return jsonify({'error': 'Unauthorized'}), 403

    quiz.shared = not quiz.shared
    db.session.commit()
    return jsonify({'shared': quiz.shared})


@app.route('/planner', methods=['GET', 'POST'])
@login_required
@update_study_streak
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
@update_study_streak
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
        session['dark_mode'] = dark_mode
        db.session.commit()
        flash('Settings updated!', 'success')

    return render_template('settings.html', user=user)


# ============================================
# ABOUT & PROFILE
# ============================================

@app.route('/about')
@login_required
def about():
    return render_template('about.html')


@app.route('/api/upload_profile_image', methods=['POST'])
@login_required
def upload_profile_image():
    if 'profile_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file'}), 400

    file = request.files['profile_image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    filename = f"profile_{session['user_id']}.jpg"
    filepath = os.path.join('static/uploads', filename)
    os.makedirs('static/uploads', exist_ok=True)
    file.save(filepath)
    session['user_profile_image'] = filename

    return jsonify({'success': True, 'image_url': f'/static/uploads/{filename}'})


# ============================================
# RUN APP - Database will be recreated on each deploy
# ============================================

with app.app_context():
    db.drop_all()
    db.create_all()
    print("✅ Database recreated successfully!")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)