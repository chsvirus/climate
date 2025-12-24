"""
Climate Control System - Cloud Version
Deployed on Render.com (free tier)
Raspberry Pi streams data to cloud server
"""

from flask import Flask, render_template, jsonify, send_file, request
from flask_socketio import SocketIO
from flask_cors import CORS
import os
from datetime import datetime
from pathlib import Path
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'climate-cloud-2024')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Data storage
DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)
CSV_FILE = DATA_DIR / 'climate_data.csv'

# Global state (updated by Raspberry Pi)
current_state = {
    'cam1': {'min': 0, 'max': 0, 'avg': 0, 'active': False},
    'cam2': {'min': 0, 'max': 0, 'avg': 0, 'active': False},
    'arduino': {
        'temperature': 0, 'humidity': 0, 'pmv': 0,
        'air_velocity_arduino': 0.0,  # Arduino's air velocity
        'ac_fan': False, 'vent_fan': False,
        'shutter1': 'UNKNOWN', 'shutter2': 'UNKNOWN',
        'connected': False
    },
    'air_velocity_raspi': 0.0,  # Raspberry Pi's air velocity
    'frame_count': 0,
    'last_update': 'Never',
    'cam1_image': None,
    'cam2_image': None
}

# Initialize CSV
def init_csv():
    if not CSV_FILE.exists():
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Timestamp', 'Frame',
                'Cam1_Min', 'Cam1_Max', 'Cam1_Avg',
                'Cam2_Min', 'Cam2_Max', 'Cam2_Avg',
                'Air_Vel_Arduino', 'Air_Vel_Raspi',
                'Temp', 'Humidity', 'PMV',
                'AC_Fan', 'Vent_Fan', 'Shutter1', 'Shutter2'
            ])

init_csv()

# ==================== API ENDPOINTS ====================

@app.route('/')
def index():
    """Main dashboard"""
    return render_template('dashboard_cloud.html')

@app.route('/api/state')
def get_state():
    """Get current system state"""
    return jsonify(current_state)

@app.route('/api/update', methods=['POST'])
def update_data():
    """Receive data from Raspberry Pi"""
    global current_state
    
    try:
        data = request.json
        
        # Update state
        if 'cam1' in data:
            current_state['cam1'] = data['cam1']
        if 'cam2' in data:
            current_state['cam2'] = data['cam2']
        if 'arduino' in data:
            current_state['arduino'] = data['arduino']
        if 'air_velocity' in data:
            current_state['air_velocity'] = data['air_velocity']
        if 'frame_count' in data:
            current_state['frame_count'] = data['frame_count']
        
        current_state['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Log to CSV
        if 'log_data' in data and data['log_data']:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            row = [
                timestamp,
                current_state.get('frame_count', 0),
                current_state['cam1'].get('min', ''),
                current_state['cam1'].get('max', ''),
                current_state['cam1'].get('avg', ''),
                current_state['cam2'].get('min', ''),
                current_state['cam2'].get('max', ''),
                current_state['cam2'].get('avg', ''),
                current_state['arduino'].get('air_velocity_arduino', ''),  # Arduino air
                current_state.get('air_velocity_raspi', ''),  # Raspi air
                current_state['arduino'].get('temperature', ''),
                current_state['arduino'].get('humidity', ''),
                current_state['arduino'].get('pmv', ''),
                current_state['arduino'].get('ac_fan', ''),
                current_state['arduino'].get('vent_fan', ''),
                current_state['arduino'].get('shutter1', ''),
                current_state['arduino'].get('shutter2', '')
            ]
            
            with open(CSV_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(row)
        
        # Broadcast to all connected clients
        socketio.emit('update', current_state)
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/upload_image', methods=['POST'])
def upload_image():
    """Receive thermal images from Raspberry Pi"""
    global current_state
    
    try:
        data = request.json
        
        if 'cam1' in data:
            current_state['cam1_image'] = data['cam1']
        if 'cam2' in data:
            current_state['cam2_image'] = data['cam2']
        
        # Broadcast images
        socketio.emit('images', {
            'cam1': current_state.get('cam1_image'),
            'cam2': current_state.get('cam2_image')
        })
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/images')
def get_images():
    """Get current thermal images"""
    return jsonify({
        'cam1': current_state.get('cam1_image'),
        'cam2': current_state.get('cam2_image')
    })

@app.route('/api/csv')
def get_csv_data():
    """Get CSV data for table view"""
    if not CSV_FILE.exists():
        return jsonify({'error': 'No data available'})
    
    try:
        with open(CSV_FILE, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        if len(rows) <= 1:
            return jsonify({'error': 'CSV file is empty'})
        
        columns = rows[0]
        data = rows[-100:] if len(rows) > 100 else rows[1:]
        
        return jsonify({
            'columns': columns,
            'data': data,
            'total': len(rows) - 1
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/graph', methods=['POST'])
def generate_graph():
    """Generate graph from CSV data"""
    if not CSV_FILE.exists():
        return jsonify({'error': 'No data available'})
    
    try:
        with open(CSV_FILE, 'r') as f:
            reader = csv.DictReader(f)
            data_dict = {}
            for row in reader:
                for key, value in row.items():
                    if key not in data_dict:
                        data_dict[key] = []
                    try:
                        data_dict[key].append(float(value))
                    except:
                        data_dict[key].append(value)
        
        graph_type = request.json.get('type', 'line')
        columns = request.json.get('columns', [])
        
        if len(columns) == 0:
            return jsonify({'error': 'No columns selected'})
        
        plt.figure(figsize=(14, 7))
        plt.style.use('dark_background')
        
        if graph_type == 'line':
            for col in columns:
                if col in data_dict:
                    plt.plot(data_dict[col], label=col, linewidth=2, marker='o', markersize=3)
            plt.xlabel('Sample', fontsize=12)
            plt.ylabel('Value', fontsize=12)
            plt.title('Time Series Plot', fontsize=14, fontweight='bold')
            plt.legend(fontsize=10)
            plt.grid(True, alpha=0.3)
        
        elif graph_type == 'scatter':
            for col in columns:
                if col in data_dict:
                    plt.scatter(range(len(data_dict[col])), data_dict[col], label=col, alpha=0.6, s=30)
            plt.xlabel('Sample', fontsize=12)
            plt.ylabel('Value', fontsize=12)
            plt.title('Scatter Plot', fontsize=14, fontweight='bold')
            plt.legend(fontsize=10)
            plt.grid(True, alpha=0.3)
        
        elif graph_type == 'bar':
            for col in columns:
                if col in data_dict:
                    values = data_dict[col][-20:]  # Last 20
                    plt.bar(range(len(values)), values, alpha=0.7, label=col)
            plt.xlabel('Sample', fontsize=12)
            plt.ylabel('Value', fontsize=12)
            plt.title('Bar Chart (Last 20 samples)', fontsize=14, fontweight='bold')
            plt.legend(fontsize=10)
        
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        img_b64 = base64.b64encode(buf.read()).decode()
        return jsonify({'image': f'data:image/png;base64,{img_b64}'})
    
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/download')
def download():
    """Download CSV file"""
    if CSV_FILE.exists():
        return send_file(
            CSV_FILE,
            as_attachment=True,
            download_name=f'climate_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    return "No data available", 404

@app.route('/health')
def health():
    """Health check endpoint for Render"""
    return jsonify({
        'status': 'healthy',
        'last_update': current_state.get('last_update'),
        'frame_count': current_state.get('frame_count')
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
