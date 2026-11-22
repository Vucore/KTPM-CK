import subprocess
import sys
import time
from contextlib import ExitStack

SERVICES = {"catalog": 8001, "payment": 8002, "booking": 8000}


def main():
    processes = []
    try:
        with ExitStack() as cleanup:
            for service, port in SERVICES.items():
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        f"cinema.{service}.api:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ]
                )
                cleanup.callback(stop, process)
                processes.append(process)
            print("Giao diện đặt vé: http://127.0.0.1:8000", flush=True)
            while all(process.poll() is None for process in processes):
                time.sleep(0.5)
            return next(process.returncode or 1 for process in processes if process.returncode is not None)
    except KeyboardInterrupt:
        return 0


def stop(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=12)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


if __name__ == "__main__":
    sys.exit(main())
