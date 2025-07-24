from flask import Flask, request, send_file, jsonify
import os
import tempfile
import traceback
import yt_dlp

app = Flask(__name__)

def get_av_formats(url):
    ydl_opts = {'quiet': True, 'skip_download': True, 'forcejson': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = [
            f for f in info['formats']
            if f.get('ext') == 'mp4' and f.get('acodec') != 'none' and f.get('vcodec') != 'none'
        ]
        formats = sorted(formats, key=lambda x: (x.get('height') or 0), reverse=True)
    return info, formats

@app.route('/formats', methods=['POST'])
def list_formats():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400
    try:
        info, formats = get_av_formats(url)
        if not formats:
            return jsonify({'error': 'No downloadable mp4 formats with audio+video found'}), 404
        qualities = []
        for idx, f in enumerate(formats):
            qualities.append({
                'quality': idx,
                'format_id': f['format_id'],
                'resolution': f.get('resolution') or f.get('height'),
                'height': f.get('height'),
                'note': f.get('format_note', ''),
                'filesize_approx': f.get('filesize_approx'),
                'tbr': f.get('tbr'),
            })
        return jsonify({
            'title': info.get('title'),
            'qualities': qualities
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download_video():
    data = request.get_json()
    url = data.get('url')
    quality = data.get('quality')
    resolution = data.get('resolution')
    if not url or (quality is None and resolution is None):
        return jsonify({'error': 'Missing url and quality or resolution parameter'}), 400
    try:
        info, formats = get_av_formats(url)
        if not formats:
            return jsonify({'error': 'No downloadable mp4 formats with audio+video found'}), 404
        fmt = None
        # Prefer resolution if provided
        if resolution is not None:
            try:
                res_int = int(resolution)
                closest = min(formats, key=lambda f: abs((f.get('height') or 0) - res_int))
                if abs((closest.get('height') or 0) - res_int) <= 20:
                    fmt = closest
                else:
                    return jsonify({'error': f'No format found for resolution {resolution}p'}), 404
            except Exception:
                return jsonify({'error': 'Invalid resolution value'}), 400
        elif quality is not None:
            try:
                fmt = formats[int(quality)]
            except (IndexError, ValueError):
                return jsonify({'error': 'Invalid quality number'}), 400
        if fmt is None:
            return jsonify({'error': 'No matching format found'}), 404
        # Use yt-dlp's default output template in a temp dir, then move to temp file
        with tempfile.TemporaryDirectory() as tmp_dir:
            ydl_outtmpl = os.path.join(tmp_dir, '%(title)s.%(ext)s')
            ydl_opts = {
                'format': fmt['format_id'],
                'outtmpl': ydl_outtmpl,
                'quiet': True,
                'no_warnings': False,
                'verbose': True,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.download([url])
            except Exception as ydl_error:
                print('yt-dlp error:', ydl_error)
                traceback.print_exc()
                return jsonify({'error': f'yt-dlp error: {ydl_error}'}), 500
            # Find the downloaded file
            files = [f for f in os.listdir(tmp_dir) if f.endswith('.mp4')]
            if not files:
                return jsonify({'error': 'Video download failed or file is empty.'}), 500
            file_path = os.path.join(tmp_dir, files[0])
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                return jsonify({'error': 'Video download failed or file is empty.'}), 500
            # Copy to a temp file for send_file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_file:
                with open(file_path, 'rb') as src:
                    tmp_file.write(src.read())
                tmp_file_path = tmp_file.name
        response = send_file(tmp_file_path, as_attachment=True, download_name=f"{info['title']}.mp4")
        @response.call_on_close
        def cleanup():
            os.remove(tmp_file_path)
        return response
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True) 