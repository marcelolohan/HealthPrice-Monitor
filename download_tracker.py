"""
Módulo de rastreamento de downloads — evita re-downloads de arquivos já baixados.

Cada pasta de download tem um arquivo .registro_downloads.json com:
  {
    "files": {
      "<nome_normalizado>": {
        "nome_original": "...",
        "baixado_em": "2026-03-14T...",
        "tamanho": 12345,
        "chave_portal": "..."   # chave da URL do portal (opcional)
      }
    }
  }

Uso nos scripts:
  from download_tracker import DownloadTracker
  tracker = DownloadTracker(download_dir)
  if tracker.ja_baixado("Materiais 2026 SPS.xlsx"):
      continue
  # ... faz download ...
  tracker.registrar("Materiais 2026 SPS.xlsx", chave_portal="?id=123")
"""

import os
import json
import re
from datetime import datetime


REGISTRO_FILE = ".registro_downloads.json"


def _normalizar(nome: str) -> str:
    """
    Remove data e versão do nome para comparação fuzzy.
    Ex: 'Materiais 2026 SPS.xlsx' == 'Materiais 2026 SPS (1).xlsx'
    """
    base = os.path.splitext(nome)[0]
    # Remove sufixos como " (1)", " - copia", datas yyyymmdd, espaços extras
    base = re.sub(r'\s*\(\d+\)\s*$', '', base)
    base = re.sub(r'\s*-\s*c[oó]pia\s*$', '', base, flags=re.IGNORECASE)
    base = re.sub(r'\b\d{8}\b', '', base)       # datas coladas
    base = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', base)  # datas com traço
    return base.strip().lower()


class DownloadTracker:
    def __init__(self, pasta: str):
        self.pasta = pasta
        self.reg_path = os.path.join(pasta, REGISTRO_FILE)
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.isfile(self.reg_path):
            try:
                with open(self.reg_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    # compatibilidade com formato antigo (lista simples)
                    if isinstance(d, dict) and "files" in d:
                        return d
            except Exception:
                pass
        return {"files": {}}

    def _save(self):
        try:
            with open(self.reg_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── Verificações ─────────────────────────────────────────────────────────

    def ja_baixado(self, nome: str, chave_portal: str = None) -> bool:
        """
        Retorna True se o arquivo já foi baixado e ainda existe em disco.
        Verifica:
          1. Pelo nome normalizado no registro
          2. Pela chave_portal no registro (se fornecida)
          3. Pelo arquivo físico na pasta (com nome normalizado)
        """
        nome_norm = _normalizar(nome)

        # 1. Registro por nome normalizado
        if nome_norm in self._data["files"]:
            entry = self._data["files"][nome_norm]
            caminho = os.path.join(self.pasta, entry.get("nome_original", nome))
            if os.path.isfile(caminho):
                return True
            # arquivo sumiu — remove do registro
            del self._data["files"][nome_norm]
            self._save()

        # 2. Registro por chave do portal
        if chave_portal:
            for entry in self._data["files"].values():
                if entry.get("chave_portal") == chave_portal:
                    caminho = os.path.join(self.pasta, entry.get("nome_original", ""))
                    if os.path.isfile(caminho):
                        return True

        # 3. Arquivo físico com nome normalizado semelhante
        try:
            for arq in os.listdir(self.pasta):
                if arq.startswith("."):
                    continue
                if _normalizar(arq) == nome_norm:
                    # registra para próximas checagens
                    self.registrar(arq)
                    return True
        except Exception:
            pass

        return False

    def registrar(self, nome: str, chave_portal: str = None):
        """Registra um arquivo como baixado."""
        nome_norm = _normalizar(nome)
        caminho = os.path.join(self.pasta, nome)
        tamanho = 0
        try:
            tamanho = os.path.getsize(caminho)
        except Exception:
            pass
        self._data["files"][nome_norm] = {
            "nome_original": nome,
            "baixado_em": datetime.now().isoformat(),
            "tamanho": tamanho,
            "chave_portal": chave_portal,
        }
        self._save()

    def limpar_invalidos(self):
        """Remove do registro arquivos que não existem mais em disco."""
        removidos = []
        for chave, entry in list(self._data["files"].items()):
            caminho = os.path.join(self.pasta, entry.get("nome_original", ""))
            if not os.path.isfile(caminho):
                removidos.append(chave)
        for k in removidos:
            del self._data["files"][k]
        if removidos:
            self._save()
        return removidos
