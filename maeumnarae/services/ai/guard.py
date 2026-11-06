"""부모의 stdin 파이프가 닫히면 엔진을 종료하는 독립 감시 프로세스."""
import os
import subprocess
import sys
import threading


def main():
    # 인증키는 argv나 디스크에 쓰지 않고 stdin 첫 줄로 전달한다.
    key = sys.stdin.buffer.readline(256).decode('ascii').strip()
    if not key:
        return 2
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(('LLAMA_', 'HF_', 'HUGGING_FACE_'))}
    environment['LLAMA_API_KEY'] = key
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    child = subprocess.Popen(sys.argv[sys.argv.index('--ai-engine-guard') + 1:],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=environment, creationflags=flags)

    def watch_parent():
        sys.stdin.buffer.read()
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()

    threading.Thread(target=watch_parent, daemon=True).start()
    return child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
