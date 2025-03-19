from flask import Flask, request, jsonify, session, redirect, url_for, render_template, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import timedelta
import pandas as pd
from io import BytesIO

# Initialize Flask application
app = Flask(__name__)

# Configuration
app.secret_key = os.urandom(24)  # Secure secret key for sessions
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'  # SQLite database
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_FILE_DIR'] = os.path.join(os.getcwd(), 'flask_session')
app.config['SESSION_USE_SIGNER'] = True  # Add signature to cookies for security

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Create session directory if it doesn't exist
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# Models
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)  # Store hashed password
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False)

    def __repr__(self):
        return f'<User {self.email} - Role: {self.role}>'

class Projects(db.Model):
    __tablename__ = 'projects'
    project_id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(50))
    group_id = db.Column(db.Integer)

    def __repr__(self):
        return f'<Project {self.project_name}>'

class Scores(db.Model):
    __tablename__ = 'scores'
    score_id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), nullable=False)
    score_given = db.Column(db.Integer, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.project_id'), nullable=False)
    judge_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships to access related model data
    project = db.relationship('Projects', backref='scores')
    judge = db.relationship('User', backref='scores')

    def __repr__(self):
        return f'<Score {self.score_id} - Project: {self.project_id} - Judge: {self.judge_id}>'

# Context processor to inject user data into templates
@app.context_processor
def inject_user():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            return dict(current_user=user, is_logged_in=True)
        else:
            session.clear()
    return dict(current_user=None, is_logged_in=False)

# Keep session alive by updating it on every request
@app.before_request
def make_session_permanent():
    session.permanent = True
    session.modified = True

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about_us.html')

@app.route('/admin/import/users', methods=['POST'])
def import_users():
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        flash('You are not authorized to perform this action.', 'error')
        return redirect(url_for('dashboard'))

    file = request.files.get('file')
    if not file or file.filename == '':
        flash('No file uploaded.', 'error')
        return redirect(url_for('dashboard'))

    try:
        df = pd.read_excel(file)
        df.columns = df.columns.str.strip()  # Remove leading/trailing spaces
        col_map = {col.lower(): col for col in df.columns}  # Case-insensitive mapping
        required = ['email', 'name', 'role']
        if not all(key in col_map for key in required):
            missing = [key for key in required if key not in col_map]
            flash(f'Missing required columns: {", ".join(missing)}', 'error')
            return redirect(url_for('dashboard'))

        email_col = col_map['email']
        name_col = col_map['name']
        role_col = col_map['role']
        password_col = col_map.get('password')  # Optional column

        for _, row in df.iterrows():
            # Skip rows with missing required fields
            if pd.isna(row[email_col]) or pd.isna(row[name_col]) or pd.isna(row[role_col]):
                continue
            email = str(row[email_col])
            name = str(row[name_col])
            role = str(row[role_col])
            password = str(row[password_col]) if password_col and not pd.isna(row[password_col]) else None

            user = User.query.filter_by(email=email).first()
            if user:
                user.name = name
                user.role = role
                if password:
                    user.password = generate_password_hash(password)
            else:
                hashed_password = generate_password_hash(password) if password else generate_password_hash('default_password')
                new_user = User(
                    email=email,
                    password=hashed_password,
                    name=name,
                    role=role
                )
                db.session.add(new_user)
        db.session.commit()
        flash('Users imported successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to import users: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

# Import Projects Route
@app.route('/admin/import/projects', methods=['POST'])
def import_projects():
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))

    file = request.files.get('file')
    if not file or file.filename == '':
        flash('No file uploaded', 'error')
        return redirect(url_for('dashboard'))

    try:
        df = pd.read_excel(file)
        df.columns = df.columns.str.strip()
        col_map = {col.lower(): col for col in df.columns}
        required = ['project id', 'project name', 'group id']
        if not all(key in col_map for key in required):
            missing = [key for key in required if key not in col_map]
            flash(f'Missing required columns: {", ".join(missing)}', 'error')
            return redirect(url_for('dashboard'))

        project_id_col = col_map['project id']
        project_name_col = col_map['project name']
        group_id_col = col_map['group id']

        # Convert numeric columns
        df[project_id_col] = pd.to_numeric(df[project_id_col], errors='coerce')
        df[group_id_col] = pd.to_numeric(df[group_id_col], errors='coerce')

        for _, row in df.iterrows():
            if pd.isna(row[project_id_col]) or pd.isna(row[project_name_col]) or pd.isna(row[group_id_col]):
                continue
            project_id = int(row[project_id_col])
            project_name = str(row[project_name_col])
            group_id = int(row[group_id_col])

            project = Projects.query.get(project_id)
            if project:
                project.project_name = project_name
                project.group_id = group_id
            else:
                new_project = Projects(
                    project_id=project_id,
                    project_name=project_name,
                    group_id=group_id
                )
                db.session.add(new_project)
        db.session.commit()
        flash('Projects imported successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to import projects: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

# Import Scores Route
@app.route('/admin/import/scores', methods=['POST'])
def import_scores():
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))

    file = request.files.get('file')
    if not file or file.filename == '':
        flash('No file uploaded', 'error')
        return redirect(url_for('dashboard'))

    try:
        df = pd.read_excel(file)
        df.columns = df.columns.str.strip()
        col_map = {col.lower(): col for col in df.columns}
        required = ['score id', 'category', 'score given', 'project id', 'judge id']
        if not all(key in col_map for key in required):
            missing = [key for key in required if key not in col_map]
            flash(f'Missing required columns: {", ".join(missing)}', 'error')
            return redirect(url_for('dashboard'))

        score_id_col = col_map['score id']
        category_col = col_map['category']
        score_given_col = col_map['score given']
        project_id_col = col_map['project id']
        judge_id_col = col_map['judge id']

        # Convert numeric columns
        df[score_id_col] = pd.to_numeric(df[score_id_col], errors='coerce')
        df[score_given_col] = pd.to_numeric(df[score_given_col], errors='coerce')
        df[project_id_col] = pd.to_numeric(df[project_id_col], errors='coerce')
        df[judge_id_col] = pd.to_numeric(df[judge_id_col], errors='coerce')

        for _, row in df.iterrows():
            if pd.isna(row[score_id_col]) or pd.isna(row[category_col]) or pd.isna(row[score_given_col]) or \
               pd.isna(row[project_id_col]) or pd.isna(row[judge_id_col]):
                continue
            score_id = int(row[score_id_col])
            category = str(row[category_col])
            score_given = int(row[score_given_col])
            project_id = int(row[project_id_col])
            judge_id = int(row[judge_id_col])

            score = Scores.query.get(score_id)
            if score:
                score.category = category
                score.score_given = score_given
                score.project_id = project_id
                score.judge_id = judge_id
            else:
                new_score = Scores(
                    score_id=score_id,
                    category=category,
                    score_given=score_given,
                    project_id=project_id,
                    judge_id=judge_id
                )
                db.session.add(new_score)
        db.session.commit()
        flash('Scores imported successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to import scores: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

@app.route('/admin/users', methods=['POST'])
def add_user():
    # Check if the user is an admin
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    # Get JSON data
    data = request.get_json()

    # Validate data
    if not all(k in data for k in ('email', 'password', 'name', 'role')):
        return jsonify({'error': 'Missing required fields'}), 400
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already exists'}), 400

    # Create new user
    hashed_password = generate_password_hash(data['password'])
    new_user = User(
        email=data['email'],
        password=hashed_password,
        name=data['name'],
        role=data['role']
    )
    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        'message': 'User added',
        'user': {'id': new_user.id, 'email': new_user.email, 'name': new_user.name, 'role': new_user.role}
    }), 201

# Export Users to Excel
@app.route('/admin/export/users')
def export_users():
    # Authentication check
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    # Query all users
    users = User.query.all()
    # Prepare data
    users_data = [
        {
            'ID': user.id,
            'Email': user.email,
            'Name': user.name,
            'Role': user.role
        }
        for user in users
    ]
    # Create DataFrame and Excel file
    df = pd.DataFrame(users_data)
    output = BytesIO()
    df.to_excel(output, index=False, sheet_name='Users')
    output.seek(0)
    # Send file for download
    return send_file(output, download_name='users.xlsx', as_attachment=True)

# Export Projects to Excel
@app.route('/admin/export/projects')
def export_projects():
    # Authentication check
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    # Query all projects
    projects = Projects.query.all()
    # Prepare data
    projects_data = [
        {
            'Project ID': project.project_id,
            'Project Name': project.project_name,
            'Group ID': project.group_id
        }
        for project in projects
    ]
    # Create DataFrame and Excel file
    df = pd.DataFrame(projects_data)
    output = BytesIO()
    df.to_excel(output, index=False, sheet_name='Projects')
    output.seek(0)
    # Send file for download
    return send_file(output, download_name='projects.xlsx', as_attachment=True)

# Export Scores to Excel
@app.route('/admin/export/scores')
def export_scores():
    # Authentication check
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    # Query all scores with related data
    scores = Scores.query.options(joinedload(Scores.project), joinedload(Scores.judge)).all()
    # Prepare data
    scores_data = [
        {
            'Score ID': score.score_id,
            'Category': score.category,
            'Score Given': score.score_given,
            'Project Name': score.project.project_name if score.project else 'N/A',
            'Judge Name': score.judge.name if score.judge else 'N/A'
        }
        for score in scores
    ]
    # Create DataFrame and Excel file
    df = pd.DataFrame(scores_data)
    output = BytesIO()
    df.to_excel(output, index=False, sheet_name='Scores')
    output.seek(0)
    # Send file for download
    return send_file(output, download_name='scores.xlsx', as_attachment=True)

@app.route('/audience')
def audience():
    if 'user_id' not in session:
        flash("Please log in to access the audience page.", "error")
        return redirect(url_for('login'))
    return render_template('audience.html')

@app.route('/contact')
def contact():
    return render_template('contact_us.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Handle JSON or form data
        if request.is_json:
            data = request.get_json()
            email = data.get('email')
            password = data.get('password')
            confirm_password = data.get('confirmPassword')
            name = data.get('name')
        else:
            email = request.form.get('email')
            password = request.form.get('signupPassword')
            confirm_password = request.form.get('signupConfirmPassword')
            name = request.form.get('name', email.split('@')[0]) if email else None

        # Validation
        if not email or not password or not confirm_password:
            if request.is_json:
                return jsonify({"error": "Email, password, and confirm password are required."}), 400
            flash("Email, password, and confirm password are required.", "error")
            return redirect(url_for('signup'))

        if password != confirm_password:
            if request.is_json:
                return jsonify({"error": "Passwords do not match."}), 400
            flash("Passwords do not match.", "error")
            return redirect(url_for('signup'))

        if User.query.filter_by(email=email).first():
            if request.is_json:
                return jsonify({"error": "Email already registered."}), 400
            flash("Email already registered.", "error")
            return redirect(url_for('signup'))

        # Create new user
        hashed_password = generate_password_hash(password)
        new_user = User(email=email, password=hashed_password, name=name or email.split('@')[0], role='user')
        db.session.add(new_user)
        db.session.commit()

        # Set session
        session.clear()
        session['user_id'] = new_user.id
        session.permanent = True

        if request.is_json:
            return jsonify({"message": "Account created successfully!", "redirect_url": url_for('index')}), 201
        flash("Account created successfully!", "success")
        return redirect(url_for('index'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if 'user_id' in session:
            return redirect(url_for('index'))
        return render_template('login.html')

    email = request.form.get('email')
    password = request.form.get('password')

    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password are required."}), 400

    user = User.query.filter_by(email=email).first()

    if user and check_password_hash(user.password, password):
        session.clear()
        session['user_id'] = user.id
        session['role'] = user.role
        session.permanent = True

        # Redirect based on role
        if user.role == 'admin':
            redirect_url = url_for('dashboard')
        elif user.role == 'FlaskApp':
            redirect_url = url_for('vote_casting')
        else:
            redirect_url = url_for('index')

        return jsonify({"status": "success", "redirect_url": redirect_url})
    return jsonify({"status": "error", "message": "Invalid email or password."}), 401

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash("Please log in to access the dashboard.", "error")
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        flash("You don't have permission to access this page.", "error")
        return redirect(url_for('index'))

    users = User.query.all()
    projects = Projects.query.all()
    scores = Scores.query.all()

    return render_template('dashboard.html', user=user, users=users, projects=projects, scores=scores)

@app.route('/vote_casting')
def vote_casting():
    if 'user_id' not in session:
        flash("Please log in to access vote casting.", "error")
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user or user.role not in ['FlaskApp', 'admin']:
        flash("You don't have permission to access this page.", "error")
        return redirect(url_for('index'))
    projects = Projects.query.all()
    return render_template('vote_casting.html', projects=projects)

@app.route('/get_scores/<int:project_id>', methods=['GET'])
def get_scores(project_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user = User.query.get(session['user_id'])
    if not user or user.role not in ['FlaskApp', 'admin']:
        return jsonify({'error': 'Forbidden'}), 403
    scores = Scores.query.filter_by(project_id=project_id, judge_id=user.id).all()
    scores_dict = {score.category: score.score_given for score in scores}
    return jsonify(scores_dict), 200

@app.route('/submit_vote', methods=['POST'])
def submit_vote():
    if 'user_id' not in session:
        return jsonify({'error': 'Please log in to vote'}), 401
    user = User.query.get(session['user_id'])
    if not user or user.role not in ['FlaskApp', 'admin']:
        return jsonify({'error': "You don't have permission to vote"}), 403

    data = request.get_json()
    project_id = data.get('project_id')
    scores = data.get('scores', {})

    if not project_id or not scores:
        return jsonify({'error': 'Invalid submission data'}), 400

    project = Projects.query.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    try:
        for category, score in scores.items():
            if score < 1 or score > 10:
                return jsonify({'error': f'Score for {category} must be between 1 and 10'}), 400
            existing_score = Scores.query.filter_by(
                category=category,
                project_id=project_id,
                judge_id=user.id
            ).first()
            if existing_score:
                existing_score.score_given = score
            else:
                new_score = Scores(
                    category=category,
                    score_given=score,
                    project_id=project_id,
                    judge_id=user.id
                )
                db.session.add(new_score)
        db.session.commit()
        return jsonify({'message': 'Vote submitted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to submit vote: {str(e)}'}), 500

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash("Please log in to view your profile.", "error")
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        flash("Session invalid. Please log in again.", "error")
        return redirect(url_for('login'))

    return render_template('profile.html', user=user)

@app.route('/voting/<int:project_id>')
def voting(project_id):
    if 'user_id' not in session:
        flash("Please log in to access voting.", "error")
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        flash("Session invalid. Please log in again.", "error")
        return redirect(url_for('login'))

    if user.role not in ['FlaskApp', 'admin']:
        flash("You don't have permission to access the voting page.", "error")
        return redirect(url_for('index'))

    project = Projects.query.get(project_id)
    if not project:
        flash("Project not found.", "error")
        return redirect(url_for('vote_casting'))

    existing_scores = Scores.query.filter_by(project_id=project_id, judge_id=user.id).all()

    return render_template('voting.html', project=project, existing_scores=existing_scores)

@app.route('/admin/projects', methods=['POST'])
def add_project():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized: Please log in'}), 403

    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        return jsonify({'error': 'Unauthorized: Admin access required'}), 403

    data = request.get_json()
    if not data or 'project_name' not in data or 'group_id' not in data:
        return jsonify({'error': 'Missing required fields: project_name and group_id'}), 400

    project_name = data['project_name']
    group_id = data['group_id']

    new_project = Projects(project_name=project_name, group_id=group_id)
    try:
        db.session.add(new_project)
        db.session.commit()
        return jsonify({
            'message': 'Project added successfully',
            'project': {
                'project_id': new_project.project_id,
                'project_name': new_project.project_name,
                'group_id': new_project.group_id
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to add project: {str(e)}'}), 500

@app.route('/admin/scores', methods=['POST'])
def add_score():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized: Please log in'}), 403

    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        return jsonify({'error': 'Unauthorized: Admin access required'}), 403

    data = request.get_json()
    if not data or not all(k in data for k in ('category', 'score_given', 'project_id', 'judge_id')):
        return jsonify({'error': 'Missing required fields'}), 400

    existing_score = Scores.query.filter_by(
        category=data['category'],
        project_id=int(data['project_id']),
        judge_id=int(data['judge_id'])
    ).first()

    if existing_score:
        existing_score.score_given = int(data['score_given'])
        db.session.commit()

        project = Projects.query.get(existing_score.project_id)
        judge = User.query.get(existing_score.judge_id)

        return jsonify({
            'message': 'Score updated successfully',
            'score': {
                'score_id': existing_score.score_id,
                'category': existing_score.category,
                'score_given': existing_score.score_given,
                'project_id': existing_score.project_id,
                'judge_id': existing_score.judge_id,
                'project_name': project.project_name if project else 'Unknown',
                'judge_name': judge.name if judge else 'Unknown'
            }
        }), 200
    else:
        new_score = Scores(
            category=data['category'],
            score_given=int(data['score_given']),
            project_id=int(data['project_id']),
            judge_id=int(data['judge_id'])
        )

        try:
            db.session.add(new_score)
            db.session.commit()

            project = Projects.query.get(new_score.project_id)
            judge = User.query.get(new_score.judge_id)

            return jsonify({
                'message': 'Score added successfully',
                'score': {
                    'score_id': new_score.score_id,
                    'category': new_score.category,
                    'score_given': new_score.score_given,
                    'project_id': new_score.project_id,
                    'judge_id': new_score.judge_id,
                    'project_name': project.project_name if project else 'Unknown',
                    'judge_name': judge.name if judge else 'Unknown'
            }
        }), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f'Failed to add score: {str(e)}'}), 500

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('index'))

# CRUD Routes for Admin
@app.route('/admin/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized: Please log in'}), 403

    current_user = User.query.get(session['user_id'])
    if not current_user or current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized: Admin access required'}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    if 'name' in data:
        user.name = data['name']
    if 'email' in data:
        existing_user = User.query.filter_by(email=data['email']).first()
        if existing_user and existing_user.id != user_id:
            return jsonify({'error': 'Email already in use'}), 400
        user.email = data['email']
    if 'role' in data:
        user.role = data['role']
    if 'password' in data and data['password']:
        user.password = generate_password_hash(data['password'])

    try:
        db.session.commit()
        return jsonify({
            'message': 'User updated successfully',
            'user': {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'role': user.role
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update user: {str(e)}'}), 500

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized: Please log in'}), 403

    current_user = User.query.get(session['user_id'])
    if not current_user or current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized: Admin access required'}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({'message': 'User deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete user: {str(e)}'}), 500

@app.route('/admin/projects/<int:project_id>', methods=['PUT'])
def update_project(project_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized: Please log in'}), 403

    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        return jsonify({'error': 'Unauthorized: Admin access required'}), 403

    project = Projects.query.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    if 'project_name' in data:
        project.project_name = data['project_name']
    if 'group_id' in data:
        project.group_id = data['group_id']

    try:
        db.session.commit()
        return jsonify({
            'message': 'Project updated successfully',
            'project': {
                'project_id': project.project_id,
                'project_name': project.project_name,
                'group_id': project.group_id
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update project: {str(e)}'}), 500

@app.route('/admin/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized: Please log in'}), 403

    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        return jsonify({'error': 'Unauthorized: Admin access required'}), 403

    project = Projects.query.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    try:
        Scores.query.filter_by(project_id=project_id).delete()
        db.session.delete(project)
        db.session.commit()
        return jsonify({'message': 'Project deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete project: {str(e)}'}), 500

@app.route('/admin/scores/<int:score_id>', methods=['PUT'])
def update_score(score_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized: Please log in'}), 403

    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        return jsonify({'error': 'Unauthorized: Admin access required'}), 403

    score = Scores.query.get(score_id)
    if not score:
        return jsonify({'error': 'Score not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    if 'category' in data:
        score.category = data['category']
    if 'score_given' in data:
        score.score_given = int(data['score_given'])
    if 'project_id' in data:
        score.project_id = int(data['project_id'])
    if 'judge_id' in data:
        score.judge_id = int(data['judge_id'])

    try:
        db.session.commit()
        project = Projects.query.get(score.project_id)
        judge = User.query.get(score.judge_id)
        return jsonify({
            'message': 'Score updated successfully',
            'score': {
                'score_id': score.score_id,
                'category': score.category,
                'score_given': score.score_given,
                'project_id': score.project_id,
                'judge_id': score.judge_id,
                'project_name': project.project_name if project else 'Unknown',
                'judge_name': judge.name if judge else 'Unknown'
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update score: {str(e)}'}), 500

@app.route('/admin/scores/<int:score_id>', methods=['DELETE'])
def delete_score(score_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized: Please log in'}), 403

    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        return jsonify({'error': 'Unauthorized: Admin access required'}), 403

    score = Scores.query.get(score_id)
    if not score:
        return jsonify({'error': 'Score not found'}), 404

    try:
        db.session.delete(score)
        db.session.commit()
        return jsonify({'message': 'Score deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete score: {str(e)}'}), 500

@app.route('/debug')
def debug():
    if app.debug:
        users = User.query.all()
        return jsonify({
            'session': dict(session),
            'users': [{'id': u.id, 'email': u.email, 'name': u.name, 'role': u.role} for u in users]
        })
    return "Debug endpoint disabled in production", 403

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        # Create test users
        test_email = 'test@example.com'
        if not User.query.filter_by(email=test_email).first():
            hashed_password = generate_password_hash('password')
            test_user = User(email=test_email, password=hashed_password, name='TestUser', role='user')
            db.session.add(test_user)
            db.session.commit()
            print(f"Created test user: {test_email} with password: password")

        judge_email = 'FlaskApp@example.com'
        if not User.query.filter_by(email=judge_email).first():
            hashed_password = generate_password_hash('judgepass')
            test_judge = User(email=judge_email, password=hashed_password, name='TestJudge', role='FlaskApp')
            db.session.add(test_judge)
            db.session.commit()
            print(f"Created test FlaskApp: {judge_email} with password: judgepass")

        admin_email = 'admin@example.com'
        if not User.query.filter_by(email=admin_email).first():
            hashed_password = generate_password_hash('admin')
            admin_user = User(email=admin_email, password=hashed_password, name='Admin', role='admin')
            db.session.add(admin_user)
            db.session.commit()
            print(f"Created test admin: {admin_email} with password: admin")

        # Create test projects
        if not Projects.query.first():
            projects = [
                Projects(project_name="Project Alpha", group_id=1),
                Projects(project_name="Project Beta", group_id=2),
                Projects(project_name="Project Gamma", group_id=3)
            ]
            db.session.add_all(projects)
            db.session.commit()
            print("Created test projects")

    app.run(debug=True)