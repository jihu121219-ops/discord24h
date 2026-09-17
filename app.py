from flask import Flask, render_template, request, jsonify, Response
import subprocess
import os
import threading
import queue
import sys
import json

app = Flask(__name__)

SLOTS_FILE = "slots_data.json"

# 기본 슬롯 구조 초기화
def load_slots():
    if os.path.exists(SLOTS_FILE):
        try:
            with open(SLOTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    # 기본 1개 슬롯
    return {
        "slot_1": {
            "name": "서버관리봇",
            "startup_file": "app.py",
            "packages": "discord.py python-dotenv",
            "status": "offline"
        }
    }

def save_slots_data(data):
    with open(SLOTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

slots_data = load_slots()
running_bots = {}  # slot_id: process
bot_logs = {}      # slot_id: queue.Queue()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_slots', methods=['GET'])
def get_slots():
    return jsonify({"status": "success", "slots": slots_data})

@app.route('/save_slots', methods=['POST'])
def save_slots():
    global slots_data
    data = request.json
    slots_data = data.get('slots', {})
    save_slots_data(slots_data)
    return jsonify({"status": "success", "message": "슬롯 설정이 저장되었습니다."})

@app.route('/add_slot', methods=['POST'])
def add_slot():
    global slots_data
    slot_id = f"slot_{len(slots_data) + 1}_" + os.urandom(2).hex()
    slots_data[slot_id] = {
        "name": f"새 봇 슬롯 {len(slots_data) + 1}",
        "startup_file": "",
        "packages": "discord.py",
        "status": "offline"
    }
    save_slots_data(slots_data)
    return jsonify({"status": "success", "slots": slots_data})

@app.route('/delete_slot', methods=['POST'])
def delete_slot():
    global slots_data
    data = request.json
    slot_id = data.get('slot_id')
    if slot_id in running_bots:
        try:
            running_bots[slot_id].terminate()
            del running_bots[slot_id]
        except:
            pass
    if slot_id in slots_data:
        del slots_data[slot_id]
        save_slots_data(slots_data)
    return jsonify({"status": "success", "slots": slots_data})

@app.route('/get_files', methods=['GET'])
def get_files():
    try:
        ignore_list = ['.cache', '.local', 'slots_data.json', 'app.py']
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

@app.route('/delete_file', methods=['POST'])
def delete_file():
    data = request.json
    filename = data.get('filename', '').strip()
    if not filename or not os.path.exists(filename):
        return jsonify({"status": "error", "message": "삭제할 파일을 찾을 수 없습니다."})
    try:
        os.remove(filename)
        return jsonify({"status": "success", "message": f"'{filename}' 파일이 삭제되었습니다."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/upload_file', methods=['POST'])
def upload_file():
    if 'files' not in request.files:
        return jsonify({"status": "error", "message": "업로드된 파일이 없습니다."})
    files = request.files.getlist('files')
    uploaded_count = 0
    try:
        for file in files:
            if file and file.filename:
                filename = file.filename
                file.save(os.path.join('.', filename))
                uploaded_count += 1
        return jsonify({"status": "success", "message": f"{uploaded_count}개의 파일이 업로드되었습니다."})
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

def read_output(process, slot_id):
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            log_line = output.strip()
            if slot_id in bot_logs:
                bot_logs[slot_id].put(log_line)

@app.route('/start_bot', methods=['POST'])
def start_bot():
    data = request.json
    slot_id = data.get('slot_id')
    
    if slot_id not in slots_data:
        return jsonify({"status": "error", "message": "존재하지 않는 슬롯입니다."})
    
    slot = slots_data[slot_id]
    filename = slot.get('startup_file', '').strip()
    packages = slot.get('packages', '').strip()

    if not filename or not filename.endswith('.py'):
        return jsonify({"status": "error", "message": "시작 설정에서 올바른 .py 파일을 지정해주세요."})
    if not os.path.exists(filename):
        return jsonify({"status": "error", "message": f"지정된 파일({filename})이 존재하지 않습니다."})
        
    if slot_id in running_bots:
        try:
            running_bots[slot_id].terminate()
        except:
            pass

    if slot_id not in bot_logs:
        bot_logs[slot_id] = queue.Queue()

    def run_with_install():
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        if packages:
            bot_logs[slot_id].put(f"[*] 패키지 설치 중: {packages}")
            try:
                pkg_list = packages.split()
                install_proc = subprocess.run(
                    [sys.executable, "-m", "pip", "install"] + pkg_list,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', env=env
                )
                for line in install_proc.stdout.splitlines():
                    bot_logs[slot_id].put(line)
                bot_logs[slot_id].put("[+] 패키지 설치 완료! 봇을 실행합니다.\n" + "="*40)
            except Exception as e:
                bot_logs[slot_id].put(f"[-] 패키지 설치 오류: {e}")

        process = subprocess.Popen(
            [sys.executable, '-u', filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            env=env
        )
        running_bots[slot_id] = process
        slots_data[slot_id]['status'] = 'online'
        threading.Thread(target=read_output, args=(process, slot_id), daemon=True).start()

    threading.Thread(target=run_with_install, daemon=True).start()
    return jsonify({"status": "success", "message": f"[{slot['name']}] '{filename}' 구동 시작..."})

@app.route('/stop_bot', methods=['POST'])
def stop_bot():
    data = request.json
    slot_id = data.get('slot_id')
    if slot_id in running_bots:
        try:
            running_bots[slot_id].terminate()
            del running_bots[slot_id]
            slots_data[slot_id]['status'] = 'offline'
            return jsonify({"status": "success", "message": "봇이 중지되었습니다."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    slots_data[slot_id]['status'] = 'offline'
    return jsonify({"status": "success", "message": "실행 중이 아니거나 이미 중지되었습니다."})

@app.route('/stream_logs/<slot_id>')
def stream_logs(slot_id):
    def generate():
        if slot_id not in bot_logs:
            bot_logs[slot_id] = queue.Queue()
        while True:
            try:
                line = bot_logs[slot_id].get(timeout=1)
                yield f"data: {line}\n\n"
            except queue.Empty:
                continue
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
