"""Supabase database layer for user management and permissions."""

import bcrypt
from flask import current_app

# All features that can have permissions
FEATURES = [
    ('timeclock', 'Time Clock', 'Clock in/out, view own status'),
    ('timeclock_history', 'Time History', 'View attendance history and summaries'),
    ('time_allocation', 'Time Allocation', 'Allocate team time to jobs'),
    ('jobs', 'Jobs', 'View jobs dashboard and job details'),
    ('jobs_edit', 'Job Editing', 'Edit job fields and save changes'),
    ('entries', 'Entries', 'View and create analytic entries'),
    ('reports', 'Reports', 'View financial reports'),
    ('export', 'Export', 'Export data (CSV, PDF)'),
    ('admin', 'Admin', 'Manage users and permissions'),
]


def get_supabase():
    """Get the Supabase client from the Flask app."""
    return current_app.supabase


def hash_password(password):
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password, password_hash):
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def create_user(username, password, full_name, email=None, employee_id=None):
    """Create a new app user in Supabase."""
    sb = get_supabase()
    pw_hash = hash_password(password)

    result = sb.table('app_users').insert({
        'username': username.strip().lower(),
        'password_hash': pw_hash,
        'full_name': full_name.strip(),
        'email': email.strip() if email else None,
        'employee_id': employee_id,
        'is_active': True,
    }).execute()

    if result.data:
        user = result.data[0]
        # Create default permissions (all false)
        for feature_key, _, _ in FEATURES:
            sb.table('user_permissions').insert({
                'user_id': user['id'],
                'feature': feature_key,
                'can_read': False,
                'can_write': False,
                'can_delete': False,
            }).execute()
        return user
    return None


def verify_user(username, password):
    """Verify username/password. Returns user dict or None."""
    sb = get_supabase()
    result = sb.table('app_users').select('*').eq(
        'username', username.strip().lower()
    ).eq('is_active', True).execute()

    if not result.data:
        return None

    user = result.data[0]
    if verify_password(password, user['password_hash']):
        return user
    return None


def get_user(user_id):
    """Get a single user by ID."""
    sb = get_supabase()
    result = sb.table('app_users').select('*').eq('id', user_id).execute()
    return result.data[0] if result.data else None


def update_user(user_id, data):
    """Update user fields (full_name, email, employee_id, is_active)."""
    sb = get_supabase()
    sb.table('app_users').update(data).eq('id', user_id).execute()


def update_password(user_id, new_password):
    """Update a user's password."""
    sb = get_supabase()
    pw_hash = hash_password(new_password)
    sb.table('app_users').update({'password_hash': pw_hash}).eq('id', user_id).execute()


def list_users():
    """Get all users."""
    sb = get_supabase()
    result = sb.table('app_users').select('*').order('full_name').execute()
    return result.data or []


def delete_user(user_id):
    """Delete a user and their permissions (cascade)."""
    sb = get_supabase()
    sb.table('app_users').delete().eq('id', user_id).execute()


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def get_user_permissions(user_id):
    """Get permissions for a user as a dict.

    Returns: {feature: {'read': bool, 'write': bool, 'delete': bool}, ...}
    """
    sb = get_supabase()
    result = sb.table('user_permissions').select('*').eq('user_id', user_id).execute()

    perms = {}
    for row in (result.data or []):
        perms[row['feature']] = {
            'read': row.get('can_read', False),
            'write': row.get('can_write', False),
            'delete': row.get('can_delete', False),
        }

    # Ensure all features exist in the dict
    for feature_key, _, _ in FEATURES:
        if feature_key not in perms:
            perms[feature_key] = {'read': False, 'write': False, 'delete': False}

    return perms


def update_user_permissions(user_id, permissions):
    """Update permissions for a user.

    permissions: {feature: {'read': bool, 'write': bool, 'delete': bool}, ...}
    """
    sb = get_supabase()

    for feature_key, _, _ in FEATURES:
        perm = permissions.get(feature_key, {})
        can_read = perm.get('read', False)
        can_write = perm.get('write', False)
        can_delete = perm.get('delete', False)

        # Upsert: try update first, create if not exists
        existing = sb.table('user_permissions').select('id').eq(
            'user_id', user_id
        ).eq('feature', feature_key).execute()

        if existing.data:
            sb.table('user_permissions').update({
                'can_read': can_read,
                'can_write': can_write,
                'can_delete': can_delete,
            }).eq('user_id', user_id).eq('feature', feature_key).execute()
        else:
            sb.table('user_permissions').insert({
                'user_id': user_id,
                'feature': feature_key,
                'can_read': can_read,
                'can_write': can_write,
                'can_delete': can_delete,
            }).execute()


def has_permission(permissions, feature, level='read'):
    """Check if a permissions dict grants access to a feature at a given level."""
    perm = permissions.get(feature, {})
    if level == 'read':
        return perm.get('read', False)
    elif level == 'write':
        return perm.get('write', False) or perm.get('read', False)
    elif level == 'delete':
        return perm.get('delete', False)
    return False


def user_count():
    """Count total users. Used to detect if setup is needed."""
    sb = get_supabase()
    result = sb.table('app_users').select('id', count='exact').execute()
    return result.count or 0
