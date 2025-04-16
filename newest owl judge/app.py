import secrets
import os
import re
import io  # For sending file data in response
from datetime import timedelta, datetime
from functools import wraps
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, request, jsonify, session, redirect, url_for, render_template, flash, g, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# --- Redis Integration ---
import redis as redis
r = redis.Redis(host='localhost', port=6379)

# Try importing pandas, required for import/export. Handle if not installed.
try:
    import pandas as pd
except ImportError:
    pd = None

# --- Configuration ---
app = Flask(__name__)
# Secret key: Essential for session security. Use environment variable in production.
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
# Database path: Use absolute path relative to this file.
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Session configuration: Filesystem-based sessions.
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
# Ensure session directory exists relative to the app file
session_dir = os.path.join(basedir, 'flask_session')
os.makedirs(session_dir, exist_ok=True)
app.config['SESSION_FILE_DIR'] = session_dir
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# --- Database Initialization ---
db = SQLAlchemy(app)

# --- Database Models ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False)  # 'user', 'judge', 'admin'
    judge_request_pending = db.Column(db.Boolean, default=False, nullable=False)
    reset_token = db.Column(db.String(100), nullable=True, index=True)
    reset_token_expiration = db.Column(db.DateTime, nullable=True)
    judge_scores = db.relationship('Scores', back_populates='judge', foreign_keys='Scores.judge_id', lazy='dynamic')

    def __repr__(self):
        return f'<User {self.id}: {self.email} ({self.role})>'

    def set_password(self, password):
        if not password:
            raise ValueError("Password cannot be empty.")
        self.password = generate_password_hash(password)

    def check_password(self, password):
        if not password:
            return False
        return check_password_hash(self.password, password)

    def generate_reset_token(self):
        token = secrets.token_urlsafe(32)
        self.reset_token = token
        self.reset_token_expiration = datetime.utcnow() + timedelta(hours=1)
        return token

    def is_reset_token_valid(self, token):
        return (self.reset_token is not None and
                self.reset_token == token and
                self.reset_token_expiration is not None and
                self.reset_token_expiration > datetime.utcnow())

    def invalidate_reset_token(self):
        self.reset_token = None
        self.reset_token_expiration = None

class Projects(db.Model):
    __tablename__ = 'projects'
    project_id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(100), nullable=False, index=True)
    group_id = db.Column(db.Integer, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    scores = db.relationship('Scores', back_populates='project', cascade="all, delete-orphan", lazy='dynamic')

    def __repr__(self):
        return f'<Project {self.project_id}: {self.project_name}>'

class Scores(db.Model):
    __tablename__ = 'scores'
    score_id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), nullable=False)
    score_given = db.Column(db.Integer, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.project_id', ondelete='CASCADE'), nullable=False, index=True)
    judge_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    project = db.relationship('Projects', back_populates='scores')
    judge = db.relationship('User', back_populates='judge_scores')
    __table_args__ = (db.UniqueConstraint('project_id', 'judge_id', 'category', name='_project_judge_category_uc'),)

    def __repr__(self):
        return f'<Score {self.score_id} - Proj:{self.project_id} Judge:{self.judge_id} Cat:{self.category} Score:{self.score_given}>'

# --- Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.current_user is None:
            flash('Please log in to access this page.', 'warning')
            session['next_url'] = request.url
            return redirect(url_for('login'))
        session.pop('next_url', None)
        return f(*args, **kwargs)
    return decorated_function

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if g.current_user is None:
                flash('Please log in to access this page.', 'warning')
                session['next_url'] = request.url
                return redirect(url_for('login'))
            if g.current_user.role != role:
                flash(f'You must be an {role} to access this page.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def roles_required(roles):
    if not isinstance(roles, list):
        roles = [roles]
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if g.current_user is None:
                flash('Please log in to access this page.', 'warning')
                session['next_url'] = request.url
                return redirect(url_for('login'))
            if g.current_user.role not in roles:
                allowed_roles = ", ".join(roles)
                flash(f'You must have one of the following roles to access this page: {allowed_roles}.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- Template Filters ---
@app.template_filter('format_datetime')
def _jinja2_filter_datetime(date, fmt=None):
    if date is None:
        return 'N/A'
    if not isinstance(date, datetime):
        try:
            date = datetime.fromisoformat(date)
        except (TypeError, ValueError):
            return date
    format_str = fmt if fmt else '%Y-%m-%d %H:%M:%S'
    try:
        return date.strftime(format_str)
    except ValueError:
        return str(date)

# --- Context Processors ---
@app.context_processor
def inject_user_and_now():
    return dict(current_user=g.current_user, now=datetime.utcnow)

# --- Before Request Handlers ---
@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    g.current_user = db.session.get(User, user_id) if user_id else None

@app.before_request
def make_session_permanent():
    session.permanent = app.config['SESSION_PERMANENT']

# --- Helper Functions for Responses ---
def handle_error(message, category="error", redirect_url_name='index', is_json=None):
    is_json_request = is_json if is_json is not None else request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    if is_json_request:
        return jsonify({"status": "error", "message": message}), 400
    else:
        flash(message, category)
        return redirect(url_for(redirect_url_name))

def handle_success(message, redirect_url=None, redirect_url_name='index', is_json=None):
    is_json_request = is_json if is_json is not None else request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    redirect_target = redirect_url or url_for(redirect_url_name)
    if is_json_request:
        return jsonify({"status": "success", "message": message, "redirect_url": redirect_target}), 200
    else:
        flash(message, "success")
        return redirect(redirect_target)

# --- Redis Leaderboard Update Function ---
def update_leaderboards():
    """
    Query the total scores for each project, update a Redis sorted set, and then print out the leaderboard.
    """
    # Query the total score for each project (group by project_name)
    project_scores = db.session.query(
        Projects.project_name,
        db.func.sum(Scores.score_given).label('tot')
    ).join(Scores, Projects.project_id == Scores.project_id).group_by(Projects.project_name).all()
    
    print("Database Project Scores:", project_scores)
    
    # Convert the query result into a dictionary mapping project name to total score
    score_mapping = {project_name: tot for project_name, tot in project_scores}
    
    redis_key_name = 'Scoreboard'
    # Clear the Redis sorted set first
    r.delete(redis_key_name)
    
    # For each project, add/update the sorted set with the total score
    for project, tot in score_mapping.items():
        r.zadd(redis_key_name, {project: tot})
        print(f'Score for project "{project}" uploaded to Redis!')
    
    # Retrieve and print the ranked projects (highest score first)
    projects_ranked = r.zrevrange(redis_key_name, 0, -1, withscores=True)
    for project_bytes, score in projects_ranked:
        project_name = project_bytes.decode('utf-8')
        print(f'Project: {project_name}, Score: {score}')

# --- Routes ---
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon',
                               max_age=2592000)

@app.route('/')
def index():
    featured_projects = None
    if g.current_user and g.current_user.role in ['judge', 'admin']:
        try:
            featured_projects = Projects.query.order_by(Projects.project_name).limit(3).all()
        except Exception as e:
            app.logger.error(f"Error fetching featured projects: {e}")
            flash("Could not load featured projects.", "error")
    return render_template('index.html', featured_projects=featured_projects)

@app.route('/about')
def about():
    return render_template('about_us.html')

@app.route('/audience')
@login_required
def audience():
    return render_template('audience.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')
        if not name or not email or not message:
            flash('Please fill out all fields.', 'error')
            return render_template('contact_us.html')
        app.logger.info(f"Contact form submission: Name={name}, Email={email}, Message={message[:100]}...")
        flash('Thank you for your message! We will get back to you soon.', 'success')
        return redirect(url_for('contact'))
    return render_template('contact_us.html')

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=g.current_user)

# --- Authentication Routes ---
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if g.current_user:
        flash("You are already logged in.", "info")
        return redirect(url_for('index'))
    if request.method == 'POST':
        if not request.is_json:
            app.logger.warning("Signup attempt failed: Request content type was not JSON.")
            return jsonify({"status": "error", "message": "Invalid request format. Only JSON is accepted."}), 415
        data = request.get_json()
        if not data:
            app.logger.warning("Signup attempt failed: Empty JSON payload received.")
            return jsonify({"status": "error", "message": "Invalid JSON payload."}), 400

        email = data.get('email', '').strip()
        password = data.get('password')
        confirm_password = data.get('confirm_password')
        name = data.get('name', '').strip()
        errors = []
        if not all([email, password, confirm_password, name]):
            errors.append("All fields (Name, Email, Password, Confirm Password) are required.")
        if email and not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            errors.append("Invalid email format.")
        if password != confirm_password:
            errors.append("Passwords do not match.")
        if not password or len(password) < 12:
            errors.append("Password must be at least 12 characters long.")
        if password and not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter.")
        if password and not re.search(r"[a-z]", password):
            errors.append("Password must contain at least one lowercase letter.")
        if password and not re.search(r"[0-9]", password):
            errors.append("Password must contain at least one number.")
        if password and not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", password):
            errors.append("Password must contain at least one symbol.")
        if errors:
            app.logger.warning(f"Signup validation failed for {email}: {'; '.join(errors)}")
            return jsonify({"status": "error", "message": " ".join(errors)}), 400
        if User.query.filter(db.func.lower(User.email) == db.func.lower(email)).first():
            app.logger.warning(f"Signup attempt failed: Email '{email}' already registered.")
            return jsonify({"status": "error", "message": "Email address already registered."}), 409
        try:
            new_user = User(email=email, name=name, role='user')
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            app.logger.info(f"New user signup successful: {email} (ID: {new_user.id})")
            return jsonify({"status": "success", "message": "Account created successfully! Please log in.", "redirect_url": url_for('login')}), 201
        except ValueError as ve:
            app.logger.error(f"Password validation error during signup for {email}: {ve}")
            return jsonify({"status": "error", "message": str(ve)}), 400
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error during signup for {email}: {e}", exc_info=True)
            return jsonify({"status": "error", "message": "An error occurred during signup. Please try again."}), 500
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.current_user:
        flash("You are already logged in.", "info")
        return redirect(url_for('index'))
    if request.method == 'POST':
        if not request.is_json:
            app.logger.warning("Login attempt failed: Request content type was not JSON.")
            return jsonify({"status": "error", "message": "Invalid request format. Only JSON is accepted."}), 415
        data = request.get_json()
        if not data:
            app.logger.warning("Login attempt failed: Empty JSON payload received.")
            return jsonify({"status": "error", "message": "Invalid JSON payload."}), 400

        email = data.get('email', '').strip()
        password = data.get('password')
        if not email or not password:
            return jsonify({"status": "error", "message": "Email and password are required."}), 400
        user = User.query.filter(db.func.lower(User.email) == db.func.lower(email)).first()
        if user and user.check_password(password):
            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            app.logger.info(f"User login successful: {user.email} (ID: {user.id})")
            next_url = session.pop('next_url', None)
            if next_url:
                redirect_url = next_url
            elif user.role == 'admin':
                redirect_url = url_for('admin_dashboard')
            elif user.role == 'judge':
                redirect_url = url_for('vote_casting')
            else:
                redirect_url = url_for('index')
            return jsonify({"status": "success", "message": "Login successful!", "redirect_url": redirect_url}), 200
        else:
            app.logger.warning(f"Failed login attempt for email: {email}")
            return jsonify({"status": "error", "message": "Invalid email or password."}), 401
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash("You have been successfully logged out.", "success")
    app.logger.info(f"User logout successful: {g.current_user.email if g.current_user else 'Unknown'}")
    return redirect(url_for('index'))

@app.route('/update_name', methods=['POST'])
@login_required
def update_name():
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415
    data = request.get_json()
    new_name = data.get('name', '').strip()
    if not new_name:
        return jsonify({'status': 'error', 'message': 'Name cannot be empty.'}), 400
    user = g.current_user
    try:
        user.name = new_name
        db.session.commit()
        app.logger.info(f"User {user.id} updated name to '{new_name}'")
        return jsonify({'status': 'success', 'message': 'Name updated successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating name for user {user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while updating name.'}), 500

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415
    data = request.get_json()
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')
    user = g.current_user
    if not all([current_password, new_password, confirm_password]):
        return jsonify({'status': 'error', 'message': 'All password fields are required.'}), 400
    if not user.check_password(current_password):
        return jsonify({'status': 'error', 'message': 'Incorrect current password.'}), 401
    if new_password != confirm_password:
        return jsonify({'status': 'error', 'message': 'New passwords do not match.'}), 400
    errors = []
    if len(new_password) < 12: errors.append("Password must be at least 12 characters long.")
    if not re.search(r"[A-Z]", new_password): errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", new_password): errors.append("Password must contain at least one lowercase letter.")
    if not re.search(r"[0-9]", new_password): errors.append("Password must contain at least one number.")
    if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", new_password): errors.append("Password must contain at least one symbol.")
    if errors:
        return jsonify({'status': 'error', 'message': "Password validation failed: " + " ".join(errors)}), 400
    try:
        user.set_password(new_password)
        db.session.commit()
        app.logger.info(f"User {user.id} successfully changed their password.")
        return jsonify({'status': 'success', 'message': 'Password changed successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error changing password for user {user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while changing the password.'}), 500

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if g.current_user:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            flash('Please enter your email address.', 'warning')
            return redirect(url_for('forgot_password'))
        user = User.query.filter(db.func.lower(User.email) == db.func.lower(email)).first()
        message = 'If an account with that email exists, a password reset link has been sent. Please check your inbox (and spam folder).'
        if user:
            try:
                token = user.generate_reset_token()
                db.session.commit()
                reset_url = url_for('reset_password_with_token', token=token, _external=True)
                # Replace with actual email sending in production
                app.logger.info(f"Generated password reset token for user {user.id} ({user.email}). Reset URL: {reset_url}")
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error processing password reset request for {email}: {e}", exc_info=True)
        flash(message, 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    if g.current_user:
        return redirect(url_for('index'))
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.is_reset_token_valid(token):
        app.logger.warning(f"Invalid or expired password reset token used: {token}")
        flash('The password reset link is invalid or has expired. Please request a new one.', 'danger')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        if not new_password or not confirm_password:
            flash('Both password fields are required.', 'warning')
            return render_template('reset_password.html', token=token)
        if new_password != confirm_password:
            flash('Passwords do not match.', 'warning')
            return render_template('reset_password.html', token=token)
        errors = []
        if len(new_password) < 12: errors.append("Password must be at least 12 characters long.")
        if not re.search(r"[A-Z]", new_password): errors.append("Password must contain at least one uppercase letter.")
        if errors:
            flash("Password validation failed: " + " ".join(errors), 'warning')
            return render_template('reset_password.html', token=token)
        try:
            user.set_password(new_password)
            user.invalidate_reset_token()
            db.session.commit()
            app.logger.info(f"User {user.id} successfully reset password using token.")
            flash('Your password has been successfully reset! You can now log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error resetting password for user {user.id} with token {token}: {e}", exc_info=True)
            flash('An error occurred while resetting your password. Please try again.', 'danger')
            return render_template('reset_password.html', token=token)
    return render_template('reset_password.html', token=token)

@app.route('/request_judge_role', methods=['POST'])
@login_required
def request_judge_role():
    user = g.current_user
    if user.role != 'user':
        return jsonify({'status': 'info', 'message': f'Your current role ({user.role}) does not require a request.'}), 403
    if user.judge_request_pending:
        return jsonify({'status': 'info', 'message': 'You have already submitted a request to become a judge.'}), 409
    try:
        user.judge_request_pending = True
        db.session.commit()
        app.logger.info(f"User {user.id} ({user.email}) requested judge role.")
        return jsonify({'status': 'success', 'message': 'Your request to become a judge has been submitted. An administrator will review it.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error processing judge role request for user {user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while submitting your request. Please try again.'}), 500

@app.route('/vote')
@roles_required(['judge', 'admin'])
def vote_casting():
    projects_with_status = []
    try:
        all_projects = Projects.query.order_by(Projects.project_name).all()
        judge_id = g.current_user.id
        for project in all_projects:
            has_voted = db.session.query(
                Scores.query.filter(
                    Scores.project_id == project.project_id,
                    Scores.judge_id == judge_id
                ).exists()
            ).scalar()
            projects_with_status.append({
                'project_id': project.project_id,
                'project_name': project.project_name,
                'group_id': project.group_id,
                'description': project.description,
                'has_voted': has_voted
            })
        return render_template('vote_casting.html', projects=projects_with_status)
    except Exception as e:
        app.logger.error(f"Error loading vote casting page for judge {g.current_user.id}: {e}", exc_info=True)
        flash("Error loading projects for voting. Please try again later.", "error")
        return redirect(url_for('index'))

@app.route('/get_scores/<int:project_id>', methods=['GET'])
@roles_required(['judge', 'admin'])
def get_scores(project_id):
    try:
        project = db.session.get(Projects, project_id)
        if not project:
            return jsonify({'status': 'error', 'message': 'Project not found.'}), 404
        scores = Scores.query.filter_by(project_id=project_id, judge_id=g.current_user.id).all()
        scores_dict = {score.category: score.score_given for score in scores}
        return jsonify(scores_dict), 200
    except Exception as e:
        app.logger.error(f"Error fetching scores for project {project_id} by judge {g.current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An error occurred while fetching scores.'}), 500

@app.route('/submit_vote', methods=['POST'])
@roles_required(['judge', 'admin'])
def submit_vote():
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Invalid request format. Expecting JSON.'}), 400
    project_id = data.get('project_id')
    scores_data = data.get('scores')
    if not project_id or not scores_data or not isinstance(scores_data, dict):
        return jsonify({'status': 'error', 'message': 'Missing project_id or scores data.'}), 400
    project = db.session.get(Projects, project_id)
    if not project:
        return jsonify({'status': 'error', 'message': 'Project not found.'}), 404
    judge_id = g.current_user.id
    try:
        validated_scores = {}
        for category, score_value in scores_data.items():
            category = category.strip()
            if not category:
                return jsonify({'status': 'error', 'message': "Score category cannot be empty."}), 400
            try:
                score = int(score_value)
                MIN_SCORE = 1
                MAX_SCORE = 100
                if not MIN_SCORE <= score <= MAX_SCORE:
                    raise ValueError(f"Score for '{category}' must be between {MIN_SCORE} and {MAX_SCORE}.")
                validated_scores[category] = score
            except (ValueError, TypeError):
                return jsonify({'status': 'error', 'message': f"Invalid score value '{score_value}' for category '{category}'. Must be a whole number between {MIN_SCORE} and {MAX_SCORE}."}), 400
        for category, score in validated_scores.items():
            existing_score = Scores.query.filter_by(
                project_id=project_id,
                judge_id=judge_id,
                category=category
            ).first()
            if existing_score:
                if existing_score.score_given != score:
                    existing_score.score_given = score
                    existing_score.timestamp = datetime.utcnow()
            else:
                new_score = Scores(
                    project_id=project_id,
                    judge_id=judge_id,
                    category=category,
                    score_given=score
                )
                db.session.add(new_score)
        if True:
            db.session.commit()
            app.logger.info(f"Judge {judge_id} submitted/updated votes for project {project_id}")
            # --- Redis Integration Call ---
            update_leaderboards()
            return jsonify({'status': 'success', 'message': f'Votes for {project.project_name} submitted successfully.'}), 200
        else:
            return jsonify({'status': 'success', 'message': f'Votes for {project.project_name} submitted. No changes were needed.'}), 200
    except ValueError as ve:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error submitting vote for project {project_id} by judge {judge_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An internal error occurred while submitting votes.'}), 500

@app.route('/api/leaderboard')
def api_leaderboard():
    try:
        projects = Projects.query.all()
        leaderboard = []
        for project in projects:
            scores = project.scores.all()
            if scores:
                avg_score = sum(score.score_given for score in scores) / len(scores)
            else:
                avg_score = None
            leaderboard.append({
                "project_id": project.project_id,
                "project_name": project.project_name,
                "average_score": round(avg_score, 2) if avg_score is not None else None
            })
        leaderboard.sort(key=lambda x: (x['average_score'] if x['average_score'] is not None else -1), reverse=True)
        for i, item in enumerate(leaderboard, start=1):
            item['rank'] = i if item['average_score'] is not None else None
        return jsonify(leaderboard), 200
    except Exception as e:
        app.logger.error(f"Error generating leaderboard: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch leaderboard data."}), 500

# --- Admin Routes and CRUD Operations ---
# (The admin routes for dashboard, user, project, and score management remain as in your existing file.)
# ...
# For brevity, the rest of the admin routes are unchanged.
# ...

if __name__ == '__main__':
    # Optionally configure logging here
    log_dir = os.path.join(basedir, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'owljudge.log')
    log_level = logging.DEBUG if app.debug else logging.INFO
    file_handler = RotatingFileHandler(log_file, maxBytes=1024000, backupCount=10, delay=True)
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    file_handler.setLevel(log_level)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(log_level)
    
    app.logger.info('OwlJudge startup configured with Redis integration.')
    app.run(debug=True)
