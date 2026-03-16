import subprocess
import sys
import os

scripts = [
    "portal_Bradesco.py",
    "portal_saw.py",
    "portal_unimed.py",
]

TIMEOUT_SEGUNDOS = 600  # 10 minutos por script

base_dir = os.path.dirname(os.path.abspath(__file__))

for script in scripts:
    script_path = os.path.join(base_dir, script)
    print(f"\n{'='*50}")
    print(f"Executando: {script}")
    print('='*50)
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            cwd=base_dir,
            input=b"\n\n\n\n\n",
            timeout=TIMEOUT_SEGUNDOS,
        )
        if result.returncode != 0:
            print(f"[ERRO] {script} finalizou com codigo {result.returncode}")
        else:
            print(f"[OK] {script} concluido com sucesso")
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] {script} ultrapassou {TIMEOUT_SEGUNDOS}s e foi encerrado")
    except Exception as e:
        print(f"[ERRO] {script} falhou: {e}")

print("\nTodos os scripts foram executados.")
