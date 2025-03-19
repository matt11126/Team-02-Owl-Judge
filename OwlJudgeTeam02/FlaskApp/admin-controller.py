from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
from flask_login import login_required, current_user
from models.models import Project
from models.models import Judge
from models.models import Team
from models.models import Criteria
from services.redis_service import RedisService
from judge.models.judge import db

# Create blueprint
admin_bp = Blueprint('admin', __name__)

# Middleware to check if user is admin
@admin_bp.before_request
def check_admin():
    if not current_user.is_authenticated or current_user.role != 'admin':
        return redirect(url_for('auth.login'))

@admin_bp.route('/')
@login_required
def dashboard():
    """Admin dashboard"""
    # Get stats for dashboard
    project_count = Project.query.count()
    judge_count = Judge.query.count()
    team_count = Team.query.count()
    
    # Get active project
    active_project_id = RedisService.get_active_project()
    active_project = None
    if active_project_id:
        active_project = Project.query.get(active_project_id)
    
    return render_template('admin/dashboard.html',
                          project_count=project_count,
                          judge_count=judge_count,
                          team_count=team_count,
                          active_project=active_project)

@admin_bp.route('/projects')
@login_required
def projects():
    """Manage projects"""
    projects = Project.query.all()
    return render_template('admin/projects.html', projects=projects)

@admin_bp.route('/projects/add', methods=['GET', 'POST'])
@login_required
def add_project():
    """Add a new project"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        
        if not name:
            flash('Project name is required', 'error')
            return redirect(url_for('admin.add_project'))
        
        project = Project(name=name, description=description)
        db.session.add(project)
        db.session.commit()
        
        flash('Project added successfully', 'success')
        return redirect(url_for('admin.projects'))
    
    return render_template('admin/add_project.html')

@admin_bp.route('/projects/edit/<int:project_id>', methods=['GET', 'POST'])
@login_required
def edit_project(project_id):
    """Edit a project"""
    project = Project.query.get_or_404(project_id)
    
    if request.method == 'POST':
        project.name = request.form.get('name')
        project.description = request.form.get('description')
        project.status = request.form.get('status')
        
        db.session.commit()
        flash('Project updated successfully', 'success')
        return redirect(url_for('admin.projects'))
    
    return render_template('admin/edit_project.html', project=project)

@admin_bp.route('/judges')
@login_required
def judges():
    """Manage judges"""
    judges = Judge.query.all()
    return render_template('admin/judges.html', judges=judges)

@admin_bp.route('/judges/add', methods=['GET', 'POST'])
@login_required
def add_judge():
    """Add a new FlaskApp"""
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not name or not email or not password:
            flash('All fields are required', 'error')
            return redirect(url_for('admin.add_judge'))
        
        # Check if FlaskApp with this email already exists
        existing_judge = Judge.query.filter_by(email=email).first()
        if existing_judge:
            flash('A FlaskApp with this email already exists', 'error')
            return redirect(url_for('admin.add_judge'))
        
        judge = Judge(name=name, email=email)
        judge.set_password(password)
        db.session.add(judge)
        db.session.commit()
        
        flash('Judge added successfully', 'success')
        return redirect(url_for('admin.judges'))
    
    return render_template('admin/add_judge.html')

@admin_bp.route('/criteria')
@login_required
def criteria():
    """Manage judging criteria"""
    criteria = Criteria.query.all()
    return render_template('admin/criteria.html', criteria=criteria)

@admin_bp.route('/criteria/add', methods=['GET', 'POST'])
@login_required
def add_criteria():
    """Add new judging criteria"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        weight = request.form.get('weight', 1.0)
        
        if not name:
            flash('Criteria name is required', 'error')
            return redirect(url_for('admin.add_criteria'))
        
        criteria = Criteria(
            name=name, 
            description=description,
            weight=float(weight),
            active=True
        )
        db.session.add(criteria)
        db.session.commit()
        
        flash('Criteria added successfully', 'success')
        return redirect(url_for('admin.criteria'))
    
    return render_template('admin/add_criteria.html')

@admin_bp.route('/api/set-active-project', methods=['POST'])
@login_required
def set_active_project():
    """API endpoint to set the active project"""
    project_id = request.json.get('project_id')
    
    if not project_id:
        return jsonify({'error': 'Project ID is required'}), 400
    
    # Check if project exists
    project = Project.query.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Set as active in Redis
    RedisService.set_active_project(project_id)
    
    # Update project status in database
    # First, set all projects to inactive
    Project.query.update({Project.status: 'inactive'})
    
    # Then set this project to active
    project.status = 'active'
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Project {project.name} is now active'
    })

@admin_bp.route('/teams')
@login_required
def teams():
    """Manage teams"""
    teams = Team.query.all()
    projects = Project.query.all()
    return render_template('admin/teams.html', teams=teams, projects=projects)

@admin_bp.route('/teams/add', methods=['GET', 'POST'])
@login_required
def add_team():
    """Add a new team"""
    if request.method == 'POST':
        name = request.form.get('name')
        project_id = request.form.get('project_id')
        members = request.form.get('members')
        
        if not name or not project_id:
            flash('Team name and project are required', 'error')
            return redirect(url_for('admin.add_team'))
        
        team = Team(
            name=name,
            project_id=project_id,
            members=members
        )
        db.session.add(team)
