from flask import Blueprint, render_template, redirect, url_for, request, jsonify, abort
from flask_login import login_required, current_user
from models.project import Project
from models.criteria import Criteria
from models.vote import Vote
from models.team import Team
from services.redis_service import RedisService
from services.vote_service import VoteService
from app import db
import json

# Create blueprint
judge_bp = Blueprint('judge', __name__)

@judge_bp.route('/dashboard')
@login_required
def dashboard():
    """Judge dashboard showing active projects to evaluate"""
    # Check if user is a judge
    if current_user.role != 'judge':
        return redirect(url_for('auth.login'))
    
    # Get active projects
    projects = Project.query.filter_by(status='active').all()
    
    # Get current active project from Redis
    active_project_id = RedisService.get_active_project()
    active_project = None
    
    if active_project_id:
        active_project = Project.query.get(active_project_id)
    
    return render_template('judge/dashboard.html', 
                          projects=projects,
                          active_project=active_project)

@judge_bp.route('/vote/<int:project_id>')
@login_required
def vote_page(project_id):
    """Display voting page for a specific project"""
    # Check if user is a judge
    if current_user.role != 'judge':
        return redirect(url_for('auth.login'))
    
    # Get project details
    project = Project.query.get_or_404(project_id)
    
    # Get teams for this project
    teams = Team.query.filter_by(project_id=project_id).all()
    
    # Get criteria for judging
    criteria = Criteria.query.filter_by(active=True).all()
    
    # Check if this is the active project
    active_project_id = RedisService.get_active_project()
    is_active = str(project_id) == active_project_id
    
    # Check if judge has already voted
    existing_votes = {}
    for c in criteria:
        vote_key = f"project:{project_id}:judge:{current_user.id}:criteria:{c.id}"
        score = RedisService.redis_client.get(vote_key)
        if score:
            existing_votes[c.id] = float(score.decode('utf-8'))
    
    return render_template('judge/vote.html',
                          project=project,
                          teams=teams,
                          criteria=criteria,
                          is_active=is_active,
                          existing_votes=existing_votes)

@judge_bp.route('/api/submit-vote', methods=['POST'])
@login_required
def submit_vote():
    """API endpoint to submit votes"""
    if current_user.role != 'judge':
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Get data from request
    data = request.json
    project_id = data.get('project_id')
    votes = data.get('votes', {})
    
    if not project_id or not votes:
        return jsonify({'error': 'Missing required data'}), 400
    
    # Check if this is the active project
    active_project_id = RedisService.get_active_project()
    if str(project_id) != active_project_id:
        return jsonify({'error': 'This project is not currently active for voting'}), 400
    
    # Process each vote
    for criteria_id, score in votes.items():
        # Store vote in Redis for real-time updates
        RedisService.store_vote(project_id, current_user.id, criteria_id, score)
        
        # Store vote in database for permanent record
        VoteService.record_vote(project_id, current_user.id, criteria_id, score)
    
    # Mark that this judge has completed voting
    RedisService.judge_completed_voting(project_id, current_user.id)
    
    return jsonify({'success': True, 'message': 'Votes submitted successfully'})

@judge_bp.route('/api/check-project-status/<int:project_id>')
@login_required
def check_project_status(project_id):
    """API endpoint to check if a project is still active"""
    active_project_id = RedisService.get_active_project()
    
    return jsonify({
        'is_active': str(project_id) == active_project_id,
        'active_project_id': active_project_id
    })
