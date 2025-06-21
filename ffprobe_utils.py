import subprocess
import json

def probe_video_duration(filepath):
    """Return the duration of a video file in seconds using ffprobe."""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'json', filepath
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        info = json.loads(result.stdout)
        return float(info['format']['duration'])
    except Exception:
        return None
