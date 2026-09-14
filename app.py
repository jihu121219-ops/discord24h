from flask import Flask, render_template, request, jsonify, Response
import subprocess
import os
import threading
import queue
import sys

app = Flask(__name__)

running_bots = {}
bot_logs = {}

# 서버 시작 시 자동으로 requirements.txt가 있으면 패키지 설치 확인
def check_and_install_requirements():
    if os.path.exists("requirements.txt"):
        try:
            print("[*] requirements.txt 발견! 필요한 모듈을 확인하고 설치합니다...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "-r", "requirements.txt"])
        except Exception as e:
            print(f"[-] 자동 모듈 설치 실패: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_files', methods=['GET'])
def get_files():
    try:
        ignore_list = ['.cache', '.local', 'app.py']
        files = [f for f in os.listdir('.') if f not in ignore_list and not f.startswith('.')]
        return jsonify({"status": "success", "files": files})
    except Exception as e:
        return jsonify({"status": "error", "files": [], "message": str(e)})

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
            f.write("")
        return jsonify({"status": "success", "message": f"'{filename}' 파일이 생성되었습니다."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

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
        
        # 파이썬이 사용자 홈 디렉토리나 로컬 설치 모듈을 인식하도록 경로 강제 추가 (--user 연동)
        process = subprocess.Popen(
            [sys.executable, '-u', filename],
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

@app.route('/run_command', methods=['POST'])
def run_command():
    data = request.json
    cmd = data.get('command', '').strip()
    if not cmd:
        return jsonify({"status": "error", "message": "명령어가 비어있습니다."})
    
    # 만약 pip install 명령어라면 --user 옵션을 강제로 붙여서 초기화를 방지함
    if cmd.startswith("pip install") and "--user" not in cmd:
        cmd = cmd.replace("pip install", "pip install --user")

    def run_cmd_thread():
        cmd_key = "terminal_console"
        if cmd_key not in bot_logs:
            bot_logs[cmd_key] = queue.Queue()
        
        bot_logs[cmd_key].put(f"$ {cmd}")
        try:
            env = os.environ.coppy() if hasattr(os, 'coppy') else os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            
            process = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                env=env
            )
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    bot_logs[cmd_key].put(output.strip())
        except Exception as e:
            bot_logs[cmd_key].put(f"[-] 명령어 실행 오류: {str(e)}")

    threading.Thread(target=run_cmd_thread, daemon=True).start()
    return jsonify({"status": "success", "message": "명령어 실행 시작..."})

@app.route('/stream_logs/<target_key>')
def stream_logs(target_key):
    def generate():
        if target_key not in bot_logs:
            yield "data: 로그가 없습니다.\n\n"
            return
        while True:
            try:
                line = bot_logs[target_key].get(timeout=1)
                yield f"data: {line}\n\n"
            except queue.Empty:
                continue
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    check_and_install_requirements()
    app.run(host='0.0.0.0', port=5000, debug=True)
