# test_app.py (Enhanced for Fuller Coverage)

import pytest
import os
import json
import io
from datetime import datetime, timedelta
import tempfile # For creating temporary files for import tests

# Make sure pandas import is handled gracefully
try:
    import pandas as pd
    import openpyxl # Also needed for pandas excel operations
    PANDAS_INSTALLED = True
except ImportError:
    pd = None
    openpyxl = None
    PANDAS_INSTALLED = False

# Adjust the import based on your project structure
from app import app as flask_app, db, User, Projects, Scores # Add other models IF routes are added later

# --- Pytest Fixture Setup --- (No changes needed)
@pytest.fixture(scope='module')
def app_fixture():
    """Create and configure a new app instance for the test module."""
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", # In-memory DB
        "SECRET_KEY": "pytest-secret-key-for-testing-v2", # Changed key just in case
        "WTF_CSRF_ENABLED": False, # Disable CSRF for easier testing
        "SESSION_COOKIE_SAMESITE": "Lax",
        "LOGIN_DISABLED": False,
        "SERVER_NAME": "localhost.test", # Necessary for url_for with _external=True
        "APPLICATION_ROOT": "/",
        "PREFERRED_URL_SCHEME": "http",
        "DEBUG": True # Enable DEBUG for testing /debug-session route if needed
    })

    with flask_app.app_context():
        print("\n[Fixture] Creating test database tables...")
        db.create_all()
        print("[Fixture] Test database tables created.")

    ctx = flask_app.app_context()
    ctx.push()
    yield flask_app
    ctx.pop()

    with flask_app.app_context():
        print("\n[Fixture] Dropping test database tables...")
        db.session.remove()
        db.drop_all()
        print("[Fixture] Test database tables dropped.")

@pytest.fixture()
def client(app_fixture):
    """A test client for the app."""
    return app_fixture.test_client()

# --- Helper Functions --- (Added _login_as_role)

def _create_user(app_context, email, password, name, role='user', is_pending=False):
    """Helper to create a user directly."""
    with app_context:
        user = User.query.filter_by(email=email).first()
        if user: # Return existing user ID if already created in this context run
             return user.id
        user = User(email=email, name=name, role=role, judge_request_pending=is_pending)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    return user_id

def _create_project(app_context, name, group_id, description="Test Desc"):
    """Helper to create a project directly."""
    with app_context:
        proj = Projects.query.filter_by(project_name=name, group_id=group_id).first()
        if proj:
            return proj.project_id
        proj = Projects(project_name=name, group_id=group_id, description=description)
        db.session.add(proj)
        db.session.commit()
        project_id = proj.project_id
    return project_id

def _create_score(app_context, project_id, judge_id, category, score):
     """Helper to create a score directly."""
     with app_context:
         # Check if score already exists for this test run
         sc = Scores.query.filter_by(project_id=project_id, judge_id=judge_id, category=category).first()
         if sc:
            if sc.score_given != score: # Update if different
                 sc.score_given = score
                 db.session.commit()
            return sc.score_id
         # Create new if not found
         sc = Scores(project_id=project_id, judge_id=judge_id, category=category, score_given=score)
         db.session.add(sc)
         db.session.commit()
         score_id = sc.score_id
     return score_id

def _login(client, email, password):
    """Logs in a user via the login route."""
    return client.post('/login', json={'email': email, 'password': password})

def _logout(client):
    """Logs out the current user."""
    return client.get('/logout', follow_redirects=True)

def _get_user_by_id(app_context, user_id):
    """Gets a user by ID."""
    with app_context:
        return db.session.get(User, user_id)

def _get_project_by_id(app_context, project_id):
     """Gets a project by ID."""
     with app_context:
         return db.session.get(Projects, project_id)

def _get_score_by_id(app_context, score_id):
     """Gets a score by ID."""
     with app_context:
         return db.session.get(Scores, score_id)

def _login_as_role(client, app_context, role='user'):
    """Logs in a user with a specific role. Creates user if needed."""
    email = f'test_{role}@example.com'
    password = f'{role}Password1!'
    name = f'{role.capitalize()} User'
    is_pending = role == 'pending' # Special case for pending user
    actual_role = 'user' if is_pending else role # DB role is 'user' for pending

    user_id = None
    with app_context:
        user = User.query.filter_by(email=email).first()
        if not user:
            user_id = _create_user(app_context, email, password, name, role=actual_role, is_pending=is_pending)
        else:
            user_id = user.id

    resp = _login(client, email, password)
    assert resp.status_code == 200, f"Failed to log in as {role}"
    assert resp.json['status'] == 'success', f"Failed to log in as {role}"
    return user_id # Return the ID of the logged-in user

# --- Test Class (Keep existing tests, add new ones) ---
class TestAppWebFunctionality:
    # ... (Keep all tests from the previous version: Basic pages, Auth, Password Reset, Profile, Voting) ...

    # --- Basic Page Load Tests ---
    def test_index_page_loads(self, client):
        response = client.get('/')
        assert response.status_code == 200
        assert b"OwlJudge: KSU Project Evaluation Platform" in response.data

    def test_about_page_loads(self, client):
        response = client.get('/about')
        assert response.status_code == 200
        assert b"About OwlJudge for KSU CCSE C-Day" in response.data

    def test_contact_page_get(self, client):
        response = client.get('/contact')
        assert response.status_code == 200
        assert b"Send Us a Message" in response.data

    def test_contact_page_post(self, client):
        response = client.post('/contact', data={
            'name': 'Test Contact', 'email': 'contact@example.com', 'subject': 'Inquiry', 'message': 'Msg'
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b"Thank you for your message!" in response.data

    # --- Authentication Flow ---
    def test_signup_page_get(self, client):
        response = client.get('/signup')
        assert response.status_code == 200
        assert b"Create Your OwlJudge Account" in response.data

    def test_signup_success(self, client, app_fixture):
        response = client.post('/signup', json={
            'name': 'Sign Up Success', 'email': 'signup.success@example.com', 'password': 'ValidPassword123!', 'confirm_password': 'ValidPassword123!'
        })
        assert response.status_code == 201
        assert response.json['status'] == 'success'
        with app_fixture.app_context():
            assert User.query.filter_by(email='signup.success@example.com').count() == 1

    def test_login_page_get(self, client):
        response = client.get('/login')
        assert response.status_code == 200
        assert b"Welcome Back!" in response.data

    def test_login_and_logout(self, client, app_fixture):
        user_id = _create_user(app_fixture.app_context(), 'login.logout.test@example.com', 'loginpass123', 'Login Logout User')
        login_response = _login(client, 'login.logout.test@example.com', 'loginpass123')
        assert login_response.status_code == 200
        profile_response = client.get('/profile')
        assert profile_response.status_code == 200
        logout_response = _logout(client)
        assert logout_response.status_code == 200
        profile_response_after_logout = client.get('/profile', follow_redirects=True)
        assert b"Please log in" in profile_response_after_logout.data

    # --- Password Reset Flow ---
    def test_forgot_password_flow(self, client, app_fixture, capsys):
        user_id = _create_user(app_fixture.app_context(), 'forgotflow.test@example.com', 'oldPassword1!', 'Forgot Flow')
        client.post('/forgot_password', data={'email': 'forgotflow.test@example.com'}, follow_redirects=True)
        token = _get_user_by_id(app_fixture.app_context(), user_id).reset_token
        assert token is not None
        client.get(f'/reset_password/{token}')
        response_reset_post = client.post(f'/reset_password/{token}', data={
            'new_password': 'NewValidPassword123!', 'confirm_password': 'NewValidPassword123!'
        }, follow_redirects=True)
        assert b'password has been successfully reset' in response_reset_post.data
        user = _get_user_by_id(app_fixture.app_context(), user_id)
        assert user.check_password('NewValidPassword123!')
        login_response = _login(client, 'forgotflow.test@example.com', 'NewValidPassword123!')
        assert login_response.status_code == 200
        _logout(client)

    # --- Profile Page Interaction ---
    def test_profile_page_update_name(self, client, app_fixture):
        user_id = _login_as_role(client, app_fixture.app_context(), 'user')
        response = client.post('/update_name', json={'name': 'Name Updated Via Test'})
        assert response.status_code == 200
        user = _get_user_by_id(app_fixture.app_context(), user_id)
        assert user.name == 'Name Updated Via Test'
        _logout(client)

    def test_profile_page_change_password(self, client, app_fixture):
        user_id = _login_as_role(client, app_fixture.app_context(), 'user') # Logs in with userPassword1!
        response = client.post('/change_password', json={
            'current_password': 'userPassword1!',
            'new_password': 'NewSecurePassword123$',
            'confirm_password': 'NewSecurePassword123$'
        })
        assert response.status_code == 200
        user = _get_user_by_id(app_fixture.app_context(), user_id)
        assert user.check_password('NewSecurePassword123$')
        _logout(client)

    def test_profile_page_request_judge_role(self, client, app_fixture):
         user_id = _login_as_role(client, app_fixture.app_context(), 'user')
         response = client.post('/request_judge_role')
         assert response.status_code == 200
         user = _get_user_by_id(app_fixture.app_context(), user_id)
         assert user.judge_request_pending is True
         _logout(client)

    # --- Voting Page Interaction ---
    def test_judge_can_vote(self, client, app_fixture):
        judge_id = _login_as_role(client, app_fixture.app_context(), 'judge')
        project_id = _create_project(app_fixture.app_context(), "Judge Voting Test Proj", 601)
        vote_page_resp = client.get('/vote')
        assert vote_page_resp.status_code == 200
        payload = {
            'project_id': project_id,
            'scores': {'Innovation': 9, 'Presentation': 7} # Only submit 2 scores
        }
        response = client.post('/submit_vote', json=payload)
        assert response.status_code == 200
        with app_fixture.app_context():
            scores = Scores.query.filter_by(project_id=project_id, judge_id=judge_id).all()
            assert len(scores) == 2 # Check only 2 were created
            score_map = {s.category: s.score_given for s in scores}
            assert score_map.get('Innovation') == 9
        _logout(client)

    def test_admin_can_vote(self, client, app_fixture):
        """Test an admin can also submit votes."""
        admin_id = _login_as_role(client, app_fixture.app_context(), 'admin')
        project_id = _create_project(app_fixture.app_context(), "Admin Voting Test Proj", 602)
        vote_page_resp = client.get('/vote')
        assert vote_page_resp.status_code == 200
        payload = {
            'project_id': project_id,
            'scores': {'Overall': 85} # Admin submits one score
        }
        response = client.post('/submit_vote', json=payload)
        assert response.status_code == 200
        assert response.json['status'] == 'success'
        with app_fixture.app_context():
            scores = Scores.query.filter_by(project_id=project_id, judge_id=admin_id).all()
            assert len(scores) == 1
            assert scores[0].category == 'Overall'
            assert scores[0].score_given == 85
        _logout(client)

    def test_submit_vote_invalid_score_range(self, client, app_fixture):
        """Test submitting vote with score outside 1-100 range fails."""
        judge_id = _login_as_role(client, app_fixture.app_context(), 'judge')
        project_id = _create_project(app_fixture.app_context(), "Invalid Range Proj", 603)
        payload = {'project_id': project_id, 'scores': {'RangeTest': 101}}
        response = client.post('/submit_vote', json=payload)
        assert response.status_code == 400
        assert response.json['status'] == 'error'
        assert 'must be between 1 and 100' in response.json['message']
        _logout(client)

    def test_submit_vote_non_numeric_score(self, client, app_fixture):
        """Test submitting vote with non-numeric score fails."""
        judge_id = _login_as_role(client, app_fixture.app_context(), 'judge')
        project_id = _create_project(app_fixture.app_context(), "Non Numeric Proj", 604)
        payload = {'project_id': project_id, 'scores': {'NumericTest': 'abc'}}
        response = client.post('/submit_vote', json=payload)
        assert response.status_code == 400
        assert response.json['status'] == 'error'
        assert 'Invalid score value' in response.json['message']
        _logout(client)

    # --- Error Page Test ---
    def test_404_error_page(self, client):
        response = client.get('/a-page-that-does-not-exist-at-all')
        assert response.status_code == 404

    # --- Debug Route Test ---
    def test_debug_session_route(self, client, app_fixture):
        """Test the debug session route."""
        if not flask_app.debug:
            pytest.skip("Skipping /debug-session test because app.debug is False")

        # Test as guest
        response_guest = client.get('/debug-session')
        assert response_guest.status_code == 200
        assert response_guest.json['session'] == {}
        assert response_guest.json['g.current_user_id'] is None

        # Test as logged-in user
        user_id = _login_as_role(client, app_fixture.app_context(), 'user')
        response_user = client.get('/debug-session')
        assert response_user.status_code == 200
        assert response_user.json['session'].get('user_id') == user_id
        assert response_user.json['g.current_user_id'] == user_id
        assert response_user.json['g.current_user_role'] == 'user'
        _logout(client)

# --- NEW/ENHANCED Admin Dashboard Test Class ---
class TestAdminDashboardFullFunctionality:

    # --- Access Control ---
    def test_admin_api_access_denied_user(self, client, app_fixture):
        """Test user cannot access admin POST/PUT/DELETE APIs."""
        user_id = _login_as_role(client, app_fixture.app_context(), 'user')
        other_user_id = _create_user(app_fixture.app_context(), 'other@user.com', 'pw', 'Other')
        response_post = client.post('/admin/users', json={'name': 'x', 'email': 'y@y.com', 'password': 'Z', 'role': 'user'})
        assert response_post.status_code == 403 # Forbidden (or redirect leading to login)
        response_put = client.put(f'/admin/users/{other_user_id}', json={'name': 'a'})
        assert response_put.status_code == 403
        response_delete = client.delete(f'/admin/users/{other_user_id}')
        assert response_delete.status_code == 403
        _logout(client)

    # --- User Management ---
    def test_admin_add_user_invalid_role(self, client, app_fixture):
        """Test admin adding user with invalid role fails."""
        _login_as_admin(client, app_fixture.app_context())
        response = client.post('/admin/users', json={
            'name': 'Invalid Role User', 'email': 'invalid.role@example.com', 'password': 'VP1!', 'role': 'superadmin'
        })
        assert response.status_code == 400
        assert 'Invalid role specified' in response.json['message']
        _logout(client)

    def test_admin_update_user_nonexistent(self, client, app_fixture):
        """Test admin updating a non-existent user fails."""
        _login_as_admin(client, app_fixture.app_context())
        response = client.put('/admin/users/99999', json={'name': 'Wont Work'})
        assert response.status_code == 404
        assert 'User not found' in response.json['message']
        _logout(client)

    def test_admin_update_user_duplicate_email(self, client, app_fixture):
        """Test admin updating user to an existing email fails."""
        user1_id = _create_user(app_fixture.app_context(), 'admin.update.dup1@example.com', 'pw', 'User One')
        user2_id = _create_user(app_fixture.app_context(), 'admin.update.dup2@example.com', 'pw', 'User Two')
        _login_as_admin(client, app_fixture.app_context())
        response = client.put(f'/admin/users/{user2_id}', json={
            'email': 'admin.update.dup1@example.com' # Try to use user1's email
        })
        assert response.status_code == 409 # Conflict
        assert 'Email address is already in use' in response.json['message']
        _logout(client)

    def test_admin_delete_user_with_scores_fails(self, client, app_fixture):
        """Test admin cannot delete a judge who has scores."""
        judge_id = _create_user(app_fixture.app_context(), 'judge.with.scores@example.com', 'pw', 'Judge With Scores', role='judge')
        project_id = _create_project(app_fixture.app_context(), "Project For Score Delete Test", 901)
        _create_score(app_fixture.app_context(), project_id, judge_id, 'Sample', 50)
        _login_as_admin(client, app_fixture.app_context())

        response = client.delete(f'/admin/users/{judge_id}')
        assert response.status_code == 409 # Conflict
        assert 'Cannot delete user: They have existing scores' in response.json['message']

        # Verify user still exists
        user = _get_user_by_id(app_fixture.app_context(), judge_id)
        assert user is not None
        _logout(client)

    # --- Project Management ---
    def test_admin_add_project_missing_fields(self, client, app_fixture):
        """Test admin adding project with missing fields fails."""
        _login_as_admin(client, app_fixture.app_context())
        response = client.post('/admin/projects', json={'project_name': 'Incomplete Proj'}) # Missing group_id
        assert response.status_code == 400
        assert 'Missing required fields' in response.json['message']
        _logout(client)

    def test_admin_update_project_nonexistent(self, client, app_fixture):
        """Test admin updating non-existent project fails."""
        _login_as_admin(client, app_fixture.app_context())
        response = client.put('/admin/projects/99999', json={'project_name': 'Wont Work'})
        assert response.status_code == 404
        assert 'Project not found' in response.json['message']
        _logout(client)

    def test_admin_delete_project_and_scores(self, client, app_fixture):
        """Test admin deleting project also deletes associated scores."""
        project_id = _create_project(app_fixture.app_context(), "Project To Delete With Scores", 902)
        judge_id = _create_user(app_fixture.app_context(), 'judge.for.del.proj@example.com', 'pw', 'Judge For Del Proj', role='judge')
        score_id = _create_score(app_fixture.app_context(), project_id, judge_id, 'ScoreToDelete', 75)
        _login_as_admin(client, app_fixture.app_context())

        response = client.delete(f'/admin/projects/{project_id}')
        assert response.status_code == 200
        assert 'Project and associated scores deleted' in response.json['message']

        # Verify project and score are gone
        proj = _get_project_by_id(app_fixture.app_context(), project_id)
        score = _get_score_by_id(app_fixture.app_context(), score_id)
        assert proj is None
        assert score is None
        _logout(client)

    # --- Score Management ---
    def test_admin_add_score_invalid_project(self, client, app_fixture):
        """Test admin adding score with invalid project ID fails."""
        _login_as_admin(client, app_fixture.app_context())
        judge_id = _create_user(app_fixture.app_context(), 'score.add.judge2@example.com', 'pw', 'Score Judge 2', role='judge')
        response = client.post('/admin/scores', json={
            'project_id': 99999, 'judge_id': judge_id, 'category': 'Cat', 'score_given': 50
        })
        assert response.status_code == 404 # Not Found (Project)
        assert 'Project not found' in response.json['message']
        _logout(client)

    def test_admin_add_score_invalid_judge_role(self, client, app_fixture):
        """Test admin adding score assigned to a non-judge/non-admin user fails."""
        _login_as_admin(client, app_fixture.app_context())
        project_id = _create_project(app_fixture.app_context(), "Score Invalid Judge Proj", 903)
        user_id = _create_user(app_fixture.app_context(), 'score.add.user@example.com', 'pw', 'Score User', role='user')
        response = client.post('/admin/scores', json={
            'project_id': project_id, 'judge_id': user_id, 'category': 'Cat', 'score_given': 50
        })
        assert response.status_code == 400
        assert 'Selected user does not have judge or admin role' in response.json['message']
        _logout(client)

    def test_admin_add_score_duplicate(self, client, app_fixture):
        """Test admin adding score that already exists fails."""
        _login_as_admin(client, app_fixture.app_context())
        project_id = _create_project(app_fixture.app_context(), "Score Dup Proj", 904)
        judge_id = _create_user(app_fixture.app_context(), 'score.dup.judge@example.com', 'pw', 'Score Judge Dup', role='judge')
        _create_score(app_fixture.app_context(), project_id, judge_id, 'DuplicateCategory', 70)
        response = client.post('/admin/scores', json={
            'project_id': project_id, 'judge_id': judge_id, 'category': 'DuplicateCategory', 'score_given': 80
        })
        assert response.status_code == 409 # Conflict
        assert 'score for this category, project, and judge already exists' in response.json['message']
        _logout(client)

    def test_admin_update_score_invalid_range(self, client, app_fixture):
        """Test admin updating score to invalid range fails."""
        admin_id = _login_as_admin(client, app_fixture.app_context())
        project_id = _create_project(app_fixture.app_context(), "Score Update Invalid Proj", 905)
        judge_id = _create_user(app_fixture.app_context(), 'score.update.invalid.judge@example.com', 'pw', 'Score Judge Invalid', role='judge')
        score_id = _create_score(app_fixture.app_context(), project_id, judge_id, 'ValidCat', 60)
        response = client.put(f'/admin/scores/{score_id}', json={'score_given': 101}) # Invalid score
        assert response.status_code == 400
        assert 'Score must be between 1 and 100' in response.json['message']
        _logout(client)

    def test_admin_update_score_nonexistent(self, client, app_fixture):
        """Test admin updating non-existent score fails."""
        _login_as_admin(client, app_fixture.app_context())
        response = client.put('/admin/scores/99999', json={'score_given': 50})
        assert response.status_code == 404
        assert 'Score not found' in response.json['message']
        _logout(client)

    def test_admin_delete_score_nonexistent(self, client, app_fixture):
        """Test admin deleting non-existent score fails."""
        _login_as_admin(client, app_fixture.app_context())
        response = client.delete('/admin/scores/99999')
        assert response.status_code == 404
        assert 'Score not found' in response.json['message']
        _logout(client)

    # --- Import/Export Extended Tests ---
    @pytest.mark.skipif(not PANDAS_INSTALLED, reason="pandas library not installed")
    def test_admin_export_and_read_users(self, client, app_fixture):
        """Create users, export, then read the file to verify content."""
        admin_id = _login_as_admin(client, app_fixture.app_context())
        user1_id = _create_user(app_fixture.app_context(), 'exp.user1@example.com', 'pw', 'Export User 1', role='user')
        user2_id = _create_user(app_fixture.app_context(), 'exp.judge1@example.com', 'pw', 'Export Judge 1', role='judge', is_pending=False)
        user3_id = _create_user(app_fixture.app_context(), 'exp.pending1@example.com', 'pw', 'Export Pending 1', role='user', is_pending=True)

        response = client.get('/admin/export/users')
        assert response.status_code == 200
        assert response.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

        # Read the exported data back using pandas
        file_data = io.BytesIO(response.data)
        df = pd.read_excel(file_data, engine='openpyxl')

        # Verify expected data is present (adjust based on your test admin user etc.)
        emails = df['email'].tolist()
        roles = df['role'].tolist()
        pendings = df['judge_request_pending'].tolist()

        assert 'exp.user1@example.com' in emails
        assert 'exp.judge1@example.com' in emails
        assert 'exp.pending1@example.com' in emails
        assert 'test_admin@admin.com' in emails # The logged-in admin

        assert 'user' in roles
        assert 'judge' in roles
        assert roles.count('user') >= 2 # User and Pending
        assert roles.count('admin') >= 1

        # Find specific rows (more robust)
        user1_row = df[df['email'] == 'exp.user1@example.com'].iloc[0]
        assert user1_row['role'] == 'user'
        assert user1_row['judge_request_pending'] is False

        judge1_row = df[df['email'] == 'exp.judge1@example.com'].iloc[0]
        assert judge1_row['role'] == 'judge'
        assert judge1_row['judge_request_pending'] is False

        pending1_row = df[df['email'] == 'exp.pending1@example.com'].iloc[0]
        assert pending1_row['role'] == 'user' # Role is user
        assert pending1_row['judge_request_pending'] is True # Flag is true

        _logout(client)

    @pytest.mark.skipif(not PANDAS_INSTALLED, reason="pandas library not installed")
    def test_admin_import_users_with_errors(self, client, app_fixture):
        """Test importing users where some rows are invalid."""
        _login_as_admin(client, app_fixture.app_context())
        # User that exists
        _create_user(app_fixture.app_context(), 'import.existing@example.com', 'pw', 'Import Existing')

        df = pd.DataFrame({
            'name': ['Valid Import', 'Invalid Role User', 'Existing Email User', 'Missing Email', 'User Valid 2'],
            'email': ['valid.import@example.com', 'invalid.role@example.com', 'import.existing@example.com', '', 'valid.import2@example.com'],
            'role': ['judge', 'superjudge', 'user', 'user', 'user'], # Invalid role in row 2
            'password': ['ImportPass1!', 'ImportPass2!', 'ImportPass3!', 'ImportPass4!', 'ImportPass5!']
        })
        output = io.BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        data = {'file': (output, 'test_users_with_errors.xlsx')}

        response = client.post('/admin/import/users', data=data, content_type='multipart/form-data')

        assert response.status_code == 200 # Should still be 200 OK if *some* succeed or only warnings
        assert response.json['status'] == 'warning' # Status should indicate errors occurred
        assert 'Errors/Skipped: 3' in response.json['message'] # Expecting 3 errors
        assert len(response.json['errors']) == 3
        # Check for specific error messages (order might vary)
        error_messages = " ".join(response.json['errors'])
        assert "invalid role 'superjudge'" in error_messages
        assert "Email 'import.existing@example.com' already exists" in error_messages
        assert "missing required name or email" in error_messages # Because email was empty

        # Verify only the valid users were added
        with app_fixture.app_context():
            assert User.query.filter_by(email='valid.import@example.com').count() == 1
            assert User.query.filter_by(email='valid.import2@example.com').count() == 1
            assert User.query.filter_by(email='invalid.role@example.com').count() == 0 # Not added
            assert User.query.filter_by(email='').count() == 0 # Not added
            # Check existing user was not modified unexpectedly (e.g., password)
            existing = User.query.filter_by(email='import.existing@example.com').first()
            assert existing.name == 'Import Existing' # Name wasn't updated by the conflicting row

        _logout(client)

    # Add similar enhanced tests for Project Import/Export