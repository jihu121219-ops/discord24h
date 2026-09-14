from flask import Flask, render_template, request, jsonify, Response
import subprocess
import os
import threading
import queue

app = Flask(__name__)

running_bots = {}
bot_logs = {}

@app.route('/')
def index():
    return render_template('index.html')

# 서버 폴더 내의 모든 파일 목록 불러오기 (.py, .txt 등 전체)
@app.route('/get_files', methods=['GET'])
def get_files():
    try:
        # 시스템 폴더나 app.py 등을 제외한 관리 대상 파일들 반환
        ignore_list = ['.cache', '.local', 'app.py']
        files = [f for f in os.listdir('.') if f not in ignore_list and not f.startswith('.')]
        return jsonify({"status": "success", "files": files})
    except Exception as e:
        return jsonify({"status": "error", "files": [], "message": str(e)})

# 새 파일 생성
@app.route('/create_file', methods=['POST'])
def create_file():
    data = request.json
    filename = data.get('filename', '').strip()
    
    if not filename:
        return jsonify({"status": "error", "message": "파일 이름을 입력해주세요."})
        
    if os.path.exists(filename):
        return jsonify({"status": "error", "message": "이미 존재하는 파일 이름입니다."})
        
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("") # 빈 파일 생성
        return jsonify({"status": "success", "message": f"'{filename}' 파일이 생성되었습니다."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# 파일 내용 읽기 (편집창용)
@app.route('/read_file', methods=['GET'])
def read_file():
    filename = request.args.get('filename', '')
    if not filename or not os.path.exists(filename):
        return jsonify({"status": "error", "message": "파일을 찾을 수 없습니다."})
    
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"status": "success", "content": content})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# 파일 내용 저장 (Ctrl + S 대응)
@app.route('/save_file', methods=['POST'])
def save_file():
    data = request.json
    filename = data.get('filename', '')
    content = data.get('content', '')
    
    if not filename:
        return jsonify({"status": "error", "message": "파일 이름이 없습니다."})
        
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"status": "success", "message": f"'{filename}' 저장 완료!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

def read_output(process, bot_name):
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            log_line = output.strip()
            if bot_name in bot_logs:
                bot_logs[bot_name].put(log_line)

# 파이썬 스크립트 실행 (봇 / 셀프봇)
@app.route('/start_bot', methods=['POST'])
def start_bot():
    data = request.json
    filename = data.get('filename', '')
    
    if not filename.endswith('.py'):
        return jsonify({"status": "error", "message": "실행은 .py 확장자 파일만 가능합니다."})
        
    if not os.path.exists(filename):
        return jsonify({"status": "error", "message": "존재하지 않는 파일입니다."})
        
    if filename in running_bots:
        try:
            running_bots[filename].terminate()
        except:
            pass

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        process = subprocess.Popen(
            ['python', '-u', filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            env=env
        )
        
        running_bots[filename] = process
        bot_logs[filename] = queue.Queue()
        
        threading.Thread(target=read_output, args=(process, filename), daemon=True).start()
        
        return jsonify({"status": "success", "message": f"'{filename}' 실행을 시작했습니다!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/stop_bot', methods=['POST'])
def stop_bot():
    data = request.json
    filename = data.get('filename', '')
    
    if filename in running_bots:
        try:
            running_bots[filename].terminate()
            del running_bots[filename]
            return jsonify({"status": "success", "message": f"'{filename}' 실행이 중지되었습니다."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    return jsonify({"status": "error", "message": "실행 중인 프로세스가 없습니다."})

@app.route('/stream_logs/<filename>')
def stream_logs(filename):
    def generate():
        if filename not in bot_logs:
            yield "data: 로그가 없습니다. 실행 버튼을 눌러주세요.\n\n"
            return
        while True:
            try:
                line = bot_logs[filename].get(timeout=1)
                yield f"data: {line}\n\n"
            except queue.Empty:
                if filename not in running_bots:
                    break
                continue
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)