import os, shutil, secrets, zipfile, io, tarfile, subprocess
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename
from functools import wraps
from ldap3 import Server, Connection, ALL
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = os.getenv('FLASK_SECRET_KEY')
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER')
if UPLOAD_FOLDER and not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Hardcoded Credentials
AUTH_USERNAME = os.getenv('AUTH_USERNAME')
AUTH_PASSWORD = os.getenv('AUTH_PASSWORD')

# LDAP Configuration
LDAP_SERVER = os.getenv('LDAP_SERVER')
LDAP_ADMIN_DN = os.getenv('LDAP_ADMIN_DN')
LDAP_ADMIN_PASSWORD = os.getenv('LDAP_ADMIN_PASSWORD')
LDAP_USER_SEARCH_BASE = os.getenv('LDAP_USER_SEARCH_BASE')
LDAP_USER_ATTRIBUTE = os.getenv('LDAP_USER_ATTRIBUTE')
LOGOUT_REDIRECT_URL = os.getenv('LOGOUT_REDIRECT_URL', '/')

# Authentication Decorator
@app.before_request
def auto_login():
    # DISABLE LOGIN: Automatically log in as 'admin' to bypass login screen.
    # To re-enable login, comment out or remove this before_request hook.
    if not session.get('logged_in'):
        session['logged_in'] = True

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def check_ldap_auth(username, password):
    if not username or not password:
        return False
    try:
        server = Server(LDAP_SERVER, get_info=ALL)
        # Step 1: Bind as Admin
        admin_conn = Connection(server, user=LDAP_ADMIN_DN, password=LDAP_ADMIN_PASSWORD, authentication='SIMPLE')
        if not admin_conn.bind():
            return False
        # Step 2: Search for User
        search_filter = f"({LDAP_USER_ATTRIBUTE}={username})"
        admin_conn.search(LDAP_USER_SEARCH_BASE, search_filter, attributes=[])
        if not admin_conn.entries:
            admin_conn.unbind()
            return False
        # Step 3: Extract DN
        user_dn = admin_conn.entries[0].entry_dn
        admin_conn.unbind()
        # Step 4: Bind as User
        user_conn = Connection(server, user=user_dn, password=password, authentication='SIMPLE')
        if user_conn.bind():
            user_conn.unbind()
            return True
        return False
    except Exception:
        return False

@app.route('/login', methods=['GET', 'POST'])
def login():
    # DISABLE LOGIN: Redirect to index immediately.
    # To re-enable, remove the redirect line below.
    return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        auth_type = request.form.get('auth_type')
        
        if auth_type == 'ldap':
            if check_ldap_auth(username, password):
                session['logged_in'] = True
                return redirect(url_for('index'))
            else:
                flash('Invalid LDAP credentials')
        else:
            if username == AUTH_USERNAME and password == AUTH_PASSWORD:
                session['logged_in'] = True
                return redirect(url_for('index'))
            else:
                flash('Invalid local username or password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('email', None)
    session.pop('description', None)
    return redirect(LOGOUT_REDIRECT_URL)

@app.route('/')
# DISABLE LOGIN: Commented out session check.
# @requires_auth
def index():
    base_dir = app.config['UPLOAD_FOLDER']
    selected_dir = request.args.get('dir', '.')
    
    # Calculate hierarchical directory list for sidebar
    dirs = []
    for root, subdirs, _ in os.walk(base_dir):
        rel_path = os.path.relpath(root, base_dir)
        depth = 0 if rel_path == '.' else len(rel_path.split(os.sep))
        if depth <= 2:
            dirs.append({
                'path': rel_path,
                'name': os.path.basename(root) if rel_path != '.' else 'Root',
                'level': depth
            })
    dirs.sort(key=lambda x: x['path'])

    # Calculate breadcrumbs for "click into" navigation
    breadcrumbs = []
    if selected_dir != '.':
        path_acc = ""
        for part in selected_dir.split(os.sep):
            path_acc = os.path.join(path_acc, part) if path_acc else part
            breadcrumbs.append({'name': part, 'path': path_acc})

    target_path = os.path.abspath(os.path.join(base_dir, selected_dir))
    
    # Security check: ensure target_path is within base_dir
    if not target_path.startswith(os.path.abspath(base_dir)):
        target_path = os.path.abspath(base_dir)
        selected_dir = '.'
        breadcrumbs = []

    files = []
    # Add parent directory link if not in root
    if selected_dir != '.':
        parent_dir = os.path.dirname(selected_dir)
        if parent_dir == '': parent_dir = '.'
        files.append({'name': '..', 'is_dir': True, 'is_parent': True, 'path': parent_dir})

    for f in os.listdir(target_path):
        is_dir = os.path.isdir(os.path.join(target_path, f))
        files.append({
            'name': f,
            'is_dir': is_dir,
            'is_parent': False,
            'path': os.path.join(selected_dir, f) if selected_dir != '.' else f
        })
        
    # Sort: folders first (except parent link), then files
    files.sort(key=lambda x: (x.get('is_parent', False) is False, not x['is_dir'], x['name'].lower()))
    
    return render_template('index.html', 
                         files=files, 
                         dirs=dirs, 
                         selected_dir=selected_dir, 
                         breadcrumbs=breadcrumbs)

@app.route('/upload', methods=['POST'])
# DISABLE LOGIN: Commented out session check.
# @requires_auth
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    files = request.files.getlist('file')
    selected_dir = request.form.get('dir', '.')
    
    if selected_dir == '.' or selected_dir == '':
        return jsonify({'error': 'Uploads to the root directory are not allowed'}), 403
    
    if not files or files[0].filename == '':
        return jsonify({'error': 'No selected files'}), 400
    
    base_dir = app.config['UPLOAD_FOLDER']
    target_path = os.path.abspath(os.path.join(base_dir, selected_dir))
    
    # Security check: ensure target_path is within base_dir
    if not target_path.startswith(os.path.abspath(base_dir)):
        return jsonify({'error': 'Invalid directory'}), 403

    uploaded_count = 0
    for file in files:
        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(target_path, filename))
            uploaded_count += 1
            
    return jsonify({
        'message': f'Successfully uploaded {uploaded_count} file(s) to {selected_dir}',
        'count': uploaded_count
    })

@app.route('/create-folder', methods=['POST'])
# DISABLE LOGIN: Commented out session check.
# @requires_auth
def create_folder():
    selected_dir = request.args.get('dir', '.')
    folder_name = request.form.get('folder_name')
    
    if not folder_name:
        flash('Folder name is required')
        return redirect(url_for('index', dir=selected_dir))
    
    base_dir = app.config['UPLOAD_FOLDER']
    # Secure the folder name to prevent directory traversal
    folder_name = secure_filename(folder_name)
    target_path = os.path.abspath(os.path.join(base_dir, selected_dir, folder_name))
    
    # Security check: ensure target_path is within base_dir
    if not target_path.startswith(os.path.abspath(base_dir)):
        flash('Invalid path')
        return redirect(url_for('index', dir=selected_dir))
    
    try:
        if not os.path.exists(target_path):
            os.makedirs(target_path)
            flash(f'Folder "{folder_name}" created successfully')
        else:
            flash(f'Folder "{folder_name}" already exists')
    except Exception as e:
        flash(f'Error creating folder: {str(e)}')
        
    return redirect(url_for('index', dir=selected_dir))

@app.route('/rename', methods=['POST'])
# DISABLE LOGIN: Commented out session check.
# @requires_auth
def rename_item():
    selected_dir = request.args.get('dir', '.')
    old_name = request.form.get('old_name')
    new_name = request.form.get('new_name')
    
    if not old_name or not new_name:
        flash('Both old and new names are required')
        return redirect(url_for('index', dir=selected_dir))
    
    base_dir = app.config['UPLOAD_FOLDER']
    new_name = secure_filename(new_name)
    
    old_path = os.path.abspath(os.path.join(base_dir, selected_dir, old_name))
    new_path = os.path.abspath(os.path.join(base_dir, selected_dir, new_name))
    
    # Security check
    if not old_path.startswith(os.path.abspath(base_dir)) or not new_path.startswith(os.path.abspath(base_dir)):
        flash('Invalid path or access denied')
        return redirect(url_for('index', dir=selected_dir))
        
    try:
        if os.path.exists(new_path):
            flash(f'An item named "{new_name}" already exists')
        else:
            os.rename(old_path, new_path)
            flash(f'Renamed to "{new_name}" successfully')
    except Exception as e:
        flash(f'Error renaming: {str(e)}')
        
    return redirect(url_for('index', dir=selected_dir))

@app.route('/delete/<path:filename>', methods=['POST'])
# DISABLE LOGIN: Commented out session check.
# @requires_auth
def delete_file(filename):
    selected_dir = request.args.get('dir', '.')
    base_dir = app.config['UPLOAD_FOLDER']
    target_path = os.path.abspath(os.path.join(base_dir, selected_dir, filename))
    
    # Security check: ensure target_path is within base_dir
    if not target_path.startswith(os.path.abspath(base_dir)):
        flash('Invalid path or access denied')
        return redirect(url_for('index', dir=selected_dir))
    
    try:
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
            message = f'Folder {filename} deleted successfully'
        elif os.path.isfile(target_path):
            os.remove(target_path)
            message = f'File {filename} deleted successfully'
        else:
            return jsonify({'error': 'Item not found'}), 404
            
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
            return jsonify({'message': message})
            
        flash(message)
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
            return jsonify({'error': str(e)}), 500
        flash(f'Error deleting: {str(e)}')
        
    return redirect(url_for('index', dir=selected_dir))

@app.route('/delete-bulk', methods=['POST'])
# DISABLE LOGIN: Commented out session check.
# @requires_auth
def delete_bulk():
    data = request.json
    filenames = data.get('filenames', [])
    selected_dir = data.get('dir', '.')
    
    if not filenames:
        return jsonify({'error': 'No files selected'}), 400
        
    base_dir = app.config['UPLOAD_FOLDER']
    target_dir = os.path.abspath(os.path.join(base_dir, selected_dir))
    
    # Security check
    if not target_dir.startswith(os.path.abspath(base_dir)):
        return jsonify({'error': 'Invalid path'}), 403
        
    deleted_count = 0
    errors = []
    
    for filename in filenames:
        # Extra safety: ensure filename doesn't contain path separators
        filename = os.path.basename(filename)
        target_path = os.path.join(target_dir, filename)
        
        try:
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
                deleted_count += 1
            elif os.path.isfile(target_path):
                os.remove(target_path)
                deleted_count += 1
        except Exception as e:
            errors.append(f"Error deleting {filename}: {str(e)}")
            
    if errors and deleted_count == 0:
        return jsonify({'error': '; '.join(errors)}), 500
        
    return jsonify({
        'message': f'Successfully deleted {deleted_count} item(s)',
        'errors': errors
    })

@app.route('/download/<path:filename>')
# DISABLE LOGIN: Commented out session check.
# @requires_auth
def download_file(filename):
    selected_dir = request.args.get('dir', '.')
    base_dir = app.config['UPLOAD_FOLDER']
    target_path = os.path.abspath(os.path.join(base_dir, selected_dir, filename))
    
    # Security check: ensure target_path is within base_dir
    if not target_path.startswith(os.path.abspath(base_dir)):
        flash('Invalid path or access denied')
        return redirect(url_for('index', dir=selected_dir))
        
    if os.path.isdir(target_path):
        flash('Cannot download directories')
        return redirect(url_for('index', dir=selected_dir))
        
    directory = os.path.dirname(target_path)
    file_name = os.path.basename(target_path)
    return send_from_directory(directory, file_name, as_attachment=True)

@app.route('/download-zip', methods=['POST'])
# DISABLE LOGIN: Commented out session check.
# @requires_auth
def download_zip():
    data = request.json
    filenames = data.get('filenames', [])
    selected_dir = data.get('dir', '.')
    
    if not filenames:
        return jsonify({'error': 'No files selected'}), 400
        
    base_dir = app.config['UPLOAD_FOLDER']
    target_dir = os.path.abspath(os.path.join(base_dir, selected_dir))
    
    # Security check
    if not target_dir.startswith(os.path.abspath(base_dir)):
        return jsonify({'error': 'Invalid path'}), 403
        
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename in filenames:
            file_path = os.path.join(target_dir, filename)
            if os.path.isfile(file_path):
                zf.write(file_path, filename)
            elif os.path.isdir(file_path):
                # Optionally handle directories
                for root, _, files in os.walk(file_path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, target_dir)
                        zf.write(full_path, rel_path)
    
    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"files_{secrets.token_hex(4)}.zip"
    )

@app.route('/release', methods=['POST'])
# DISABLE LOGIN: Commented out session check.
# @requires_auth
def release():
    data = request.json
    paths = data.get('paths', [])
    path = data.get('path')
    
    if not paths and path:
        paths = [path]
    
    if not paths:
        return jsonify({'error': 'No files selected'}), 400
        
    check_only = data.get('check_only', False)
    base_dir = app.config['UPLOAD_FOLDER']
    release_dir = os.path.join(base_dir, 'release')
    
    if check_only:
        all_duplicates = []
        try:
            for p in paths:
                if not p.endswith('.tar.gz'): continue
                staging_path = os.path.join(base_dir, p)
                if not os.path.exists(staging_path): continue
                
                # Use tar -tf for speed
                cmd = ['tar', '-tf', staging_path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    members = result.stdout.splitlines()
                    for member in members:
                        if member and not member.endswith('/'): # Skip directories
                            # Normalize member path (remove leading ./)
                            clean_member = member.lstrip('./')
                            target_path = os.path.join(release_dir, clean_member)
                            
                            if os.path.exists(target_path):
                                if clean_member not in all_duplicates:
                                    all_duplicates.append(clean_member)
                                    if len(all_duplicates) > 100: # Limit list size for UI
                                        break
                if len(all_duplicates) > 100:
                    break
            
            return jsonify({
                'duplicates': all_duplicates,
                'has_duplicates': len(all_duplicates) > 0,
                'total_duplicates': len(all_duplicates)
            })
        except Exception as e:
            return jsonify({'error': f'Failed to read tarball: {str(e)}'}), 500
    else:
        # Execution phase
        extracted_count = 0
        removed_count = 0
        errors = []
        
        for p in paths:
            if not p.endswith('.tar.gz'): continue
            staging_path = os.path.join(base_dir, p)
            if not os.path.exists(staging_path):
                errors.append(f"File not found: {p}")
                continue
                
            filename = os.path.basename(p)
            target_tar_path = os.path.join(release_dir, filename)
            
            try:
                # 1. Copy tar.gz to release folder
                shutil.copy2(staging_path, target_tar_path)
                
                # 2. Extract using tar xvfz
                cmd = ['tar', 'xvfz', filename]
                result = subprocess.run(cmd, cwd=release_dir, capture_output=True, text=True)
                
                if result.returncode != 0:
                    errors.append(f"Extraction failed for {filename}: {result.stderr}")
                    continue
                
                extracted_count += 1
                
                # 3. Delete from staging
                try:
                    os.remove(staging_path)
                    removed_count += 1
                except Exception as e:
                    errors.append(f"Failed to remove {filename} from staging: {str(e)}")
                    
            except Exception as e:
                errors.append(f"Extraction failed for {filename}: {str(e)}")
        
        if extracted_count == 0 and errors:
            return jsonify({'error': '; '.join(errors)}), 500
            
        message = f'Successfully extracted {extracted_count} bundle(s)'
        if removed_count > 0:
            message += f' and removed {removed_count} from staging'
        
        if errors:
            message += f'. Errors: {"; ".join(errors)}'
            
        return jsonify({'message': message})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
