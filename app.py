import os
import sys
import json
import subprocess
import threading
from queue import Queue, Empty
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)

# 슬롯 데이터 저장 파일 경로
CONFIG_FILE = "slots_config.json"

# 전역 슬롯 상태 관리 딕셔너리 및 프로세스 관리
# 구조: { slot_id: { "name": "...", "packages": "...", "startup_file": "...", "status": "offline" } }
bot_processes = {}
bot_queues = {}

def load_slots_data():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                pass
    # 기본 초기 슬롯 설정
    return {
        "slot_1": {
            "name": "서버관리봇",
            "packages": "discord.py",
            "startup_file": "bot.py",
            "status": "offline"
        }
    }

def save_slots_data(slots):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(slots, f, ensure_ascii=False, indent=4)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_slots', methods=['GET'])
def get_slots():
    slots = load_slots_data()
    # 현재 실행 상태 확인 후 동기화
    for slot_id in slots:
        if slot_id in bot_processes and bot_processes[slot_id].poll() is None:
            slots[slot_id]["status"] = "online"
        else:
            slots[slot_id]["status"] = "offline"
    return jsonify({"slots": slots})

@app.route('/add_slot', methods=['POST'])
def add_slot():
    slots = load_slots_data()
    new_id = f"slot_{len(slots) + 1}"
    slots[new_id] = {
        "name": f"봇 슬롯 {len(slots) + 1}",
        "packages": "",
        "startup_file": "bot.py",
        "status": "offline"
    }
    save_slots_data(slots)
    return jsonify({"slots": slots})

@app.route('/save_slots', methods=['POST'])
def save_slots():
    data = request.json
    slots = data.get("slots", {})
    save_slots_data(slots)
    return jsonify({"status": "success", "message": "저장되었습니다."})

# [추가됨] 웹 화면에서 입력한 패키지를 즉시 pip로 설치하는 라우트
@app.route('/install_packages', methods=['POST'])
def install_packages():
    data = request.json
    packages = data.get('packages', '')
    
    if not packages.strip():
        return jsonify({"status": "success", "message": "저장되었습니다. (설치할 패키지 없음)"})
    
    pkg_list = packages.split()
    try:
        cmd = [sys.executable, "-m", "pip", "install"] + pkg_list
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return jsonify({"status": "success", "message": f"라이브러리 설치 성공:\n{result.stdout}"})
    except subprocess.CalledProcessError as e:
        return jsonify({"status": "error", "message": f"라이브러리 설치 중 오류 발생:\n{e.stderr}"})

@app.route('/get_files', methods=['GET'])
def get_files():
    # 현재 디렉토리 내의 파일 목록 반환 (특정 확장자 제외 가능)
    ignore_files = ['app.py', 'slots_config.json']
    files = [f for f in os.listdir('.') if os.path.isfile(f) and f not in ignore_files and not f.startswith('.')]
    return jsonify({"files": files})

@app.route('/create_file', methods=['POST'])
def create_file():
    filename = request.json.get('filename')
    if not filename:
        return jsonify({"status": "error", "message": "파일명이 없습니다."})
    if os.path.exists(filename):
        return jsonify({"status": "error", "message": "이미 존재하는 파일입니다."})
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("# 여기에 코드를 작성하세요\n")
    return jsonify({"status": "success", "message": f"'{filename}' 파일이 생성되었습니다."})

@app.route('/delete_file', methods=['POST'])
def delete_file():
    filename = request.json.get('filename')
    if filename and os.path.exists(filename):
        os.remove(filename)
        return jsonify({"status": "success", "message": f"'{filename}' 파일이 삭제되었습니다."})
    return jsonify({"status": "error", "message": "파일을 찾을 수 없습니다."})

@app.route('/upload_file', methods=['POST'])
def upload_file():
    uploaded_files = request.files.getlist("files")
    for file in uploaded_files:
        if file.filename:
            file.save(file.filename)
    return jsonify({"status": "success", "message": "파일 업로드 완료!"})

@app.route('/read_file', methods=['GET'])
def read_file():
    filename = request.args.get('filename')
    if filename and os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"status": "success", "content": content})
    return jsonify({"status": "error", "message": "파일을 읽을 수 없습니다."})

@app.route('/save_file', methods=['POST'])
def save_file():
    data = request.json
    filename = data.get('filename')
    content = data.get('content')
    if filename:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"status": "success", "message": "저장되었습니다."})
    return jsonify({"status": "error", "message": "저장 실패"})

@app.route('/start_bot', methods=['POST'])
def start_bot():
    data = request.json
    slot_id = data.get('slot_id')
    slots = load_slots_data()
    
    if slot_id not in slots:
        return jsonify({"status": "error", "message": "존재하지 않는 슬롯입니다."})
    
    # 이미 실행 중인 경우 중지 후 재시작
    if slot_id in bot_processes and bot_processes[slot_id].poll() is None:
        bot_processes[slot_id].terminate()

    startup_file = slots[slot_id].get("startup_file", "bot.py")
    if not os.path.exists(startup_file):
        return jsonify({"status": "error", "message": f"실행할 파일({startup_file})이 존재하지 않습니다."})

    q = Queue()
    bot_queues[slot_id] = q

    def enqueue_output(out, queue):
        for line in iter(out.readline, b''):
            queue.put(line.decode('utf-8', errors='ignore'))
        out.close()

    # 프로세스 실행
    process = subprocess.Popen(
        [sys.executable, startup_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=False
    )
    bot_processes[slot_id] = process

    t = threading.Thread(target=enqueue_output, args=(process.stdout, q))
    t.daemon = True
    t.start()

    return jsonify({"status": "success", "message": f"'{startup_file}' 구동이 시작되었습니다."})

@app.route('/stop_bot', methods=['POST'])
def stop_bot():
    data = request.json
    slot_id = data.get('slot_id')
    if slot_id in bot_processes and bot_processes[slot_id].poll() is None:
        bot_processes[slot_id].terminate()
        return jsonify({"status": "success", "message": "봇이 중지되었습니다."})
    return jsonify({"status": "error", "message": "실행 중인 봇이 아닙니다."})

@app.route('/stream_logs/<slot_id>')
def stream_logs(slot_id):
    def event_stream():
        q = bot_queues.get(slot_id)
        if not q:
            yield f"data: [!] 로그 스트림 대기 중...\n\n"
            return
        while True:
            try:
                line = q.get(timeout=1.0)
                yield f"data: {line.strip()}\n\n"
            except Empty:
                if slot_id in bot_processes and bot_processes[slot_id].poll() is not None:
                    yield f"data: [!] 프로세스가 종료되었습니다.\n\n"
                    break
                continue
    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
