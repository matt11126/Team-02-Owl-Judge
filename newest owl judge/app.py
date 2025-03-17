from flask import Flask, render_template, request, session, jsonify, flash, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
import os
from datetime import timedelta

app = Flask(__name__)

# Configuration
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_here')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

Session(app)
db = SQLAlchemy(app)


# Models
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False)


class Projects(db.Model):
    __tablename__ = 'projects'
    project_id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(50))
    group_id = db.Column(db.Integer)


class Scores(db.Model):
    __tablename__ = 'scores'
    score_id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), nullable=False)
    score_given = db.Column(db.Integer, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.project_id'), nullable=False)
    judge_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    def __repr__(self):
        return f'<Score {self.score_id} - Project: {self.project_id} - Judge: {self.judge_id}>'


with app.app_context():
    db.create_all()


# Keep session alive
@app.before_request
def make_session_permanent():
    session.modified = True


@app.context_processor
def inject_user():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user:  # Ensure user still exists in database
            return dict(current_user=user, is_logged_in=True)
    return dict(current_user=None, is_logged_in=False)


# Routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/about')
def about():
    return render_template('about_us.html')


@app.route('/audience')
def audience():
    return render_template('audience.html')


@app.route('/api/signup', methods=['POST'])
def api_signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 400
    hashed_password = generate_password_hash(password)
    new_user = User(email=email, password=hashed_password, name=email.split('@')[0])
    db.session.add(new_user)
    db.session.commit()
    session['user_id'] = new_user.id
    session.permanent = True
    return jsonify({'message': 'Account created successfully'}), 201


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash("Please log in to access the dashboard.", "error")
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if user.role == 'judge':
        projects = Projects.query.all()  # Fetch all projects
        return render_template('dashboard.html', projects=projects)
    return render_template('dashboard.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session.permanent = True
            flash("Logged in successfully!", "success")
            return redirect(url_for('index'))
        else:
            flash("Invalid email or password.", "error")
    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('signupPassword')
        confirm_password = request.form.get('signupConfirmPassword')
        if not email or not password:
            flash("Email and password are required.", "error")
            return redirect(url_for('signup'))
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for('signup'))
        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "error")
            return redirect(url_for('signup'))
        hashed_password = generate_password_hash(password)
        new_user = User(
            email=email,
            password=hashed_password,
            name=email.split('@')[0],
            role='user'
        )
        db.session.add(new_user)
        db.session.commit()
        session['user_id'] = new_user.id
        session.permanent = True
        flash("Account created successfully!", "success")
        return redirect(url_for('index'))
    return render_template('signup.html')


@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash("Please log in to view your profile.", "error")
        return redirect(url_for('login'))
    return render_template('profile.html')


@app.route('/contact')
def contact():
    return render_template('contact_us.html')


@app.route('/vote_casting')
def vote_casting():
    if 'user_id' not in session:
        flash("Please log in to access vote casting.", "error")
        return redirect(url_for('login'))
    return render_template('vote_casting.html')


@app.route('/voting/<int:project_id>')
def voting(project_id):
    if 'user_id' not in session:
        flash("Please log in to access voting.", "error")
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if user and user.role in ['judge']:
        project = db.session.get(Projects, project_id)
        if project:
            return render_template('voting.html', project=project)
        else:
            flash("Project not found.", "error")
            return redirect(url_for('index'))
    else:
        flash("You don't have permission to access the voting page.", "error")
        return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('index'))


@app.route('/debug')
def debug():
    if app.debug:
        users = User.query.all()
        return jsonify({
            'session': dict(session),
            'users': [{'email': u.email, 'name': u.name, 'role': u.role} for u in users]
        })
    return "Debug endpoint disabled in production", 403


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


if __name__ == '__main__':
    with app.app_context():
        test_email = 'test@example.com'
        if not User.query.filter_by(email=test_email).first():
            hashed_password = generate_password_hash('password')
            test_user = User(
                email=test_email,
                password=hashed_password,
                name='TestUser',
                role='user'
            )
            db.session.add(test_user)
            db.session.commit()
            print(f"Created test user: {test_email} with password: password")

        judge_email = 'judge@example.com'
        if not User.query.filter_by(email=judge_email).first():
            hashed_password = generate_password_hash('judgepass')
            test_judge = User(
                email=judge_email,
                password=hashed_password,
                name='TestJudge',
                role='judge'
            )
            db.session.add(test_judge)
            db.session.commit()
            print(f"Created test judge: {judge_email} with password: judgepass")

            admin_email = 'admin@example.com'
            if not User.query.filter_by(email=admin_email).first():
                hashed_password = generate_password_hash('admin')
                test_judge = User(
                    email=judge_email,
                    password=hashed_password,
                    name='admin',
                    role='admin'
                )
                db.session.add(test_judge)
                db.session.commit()
                print(f"Created test admin: {judge_email} with password: admin")


    app.run(debug=True)